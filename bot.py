import os
import time
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
API_KEY = "ce18a6d60e07f56d00d8e3860db124d3"
TELEGRAM_BOT_TOKEN = "8680294291:AAE2kV7LIL_5ET3t6iz5wl8C1LKzBKrqpkM"
TELEGRAM_CHAT_ID = "8367160484"

DELTA_THRESHOLD = 3.0  # Alert if Sharp Consensus probability shifts by 3% or more
CHECK_INTERVAL = 300   # Check every 5 minutes (300 seconds)

# List of target Sharp Bookmakers/Exchanges
SHARP_BOOKMAKERS = {'pinnacle', 'betfair_ex_uk', 'betonlineag', '1xbet', 'unibet_eu'}

# Store previous state: {match_id: {selection: probability}}
previous_state = {}


def send_telegram_alert(message):
    """Helper to send alerts directly to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram environment variables not configured.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")


def fetch_and_process_odds():
    """Fetches odds, filters sharp books, calculates Galton consensus, and alerts on shift."""
    global previous_state
    
    if not API_KEY:
        print("ODDS_API_KEY environment variable is missing.")
        return

    # Odds API Endpoint for Soccer Matches
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY}&regions=eu,uk,us&markets=h2h"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"API Error ({response.status_code}): {response.text}")
            return
        
        events = response.json()
        now = datetime.now(timezone.utc)

        for event in events:
            match_id = event.get('id')
            home_team = event.get('home_team')
            away_team = event.get('away_team')
            league = event.get('sport_title', 'Soccer')
            commence_time_str = event.get('commence_time')

            # 1. Skip Live / Finished Games (Pre-match only)
            if commence_time_str:
                commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                if commence_time <= now:
                    continue  

            bookmakers = event.get('bookmakers', [])
            if not bookmakers:
                continue

            # ---------------------------------------------------------
            # 🏛️ GALTON CONSENSUS ENGINE (SHARP BOOKS ONLY)
            # ---------------------------------------------------------
            home_probs, draw_probs, away_probs = [], [], []
            sharp_count = 0

            for bookmaker in bookmakers:
                key = bookmaker.get('key', '').lower()
                
                # Filter for sharp books (fallback to all if no sharp book found)
                if key in SHARP_BOOKMAKERS:
                    markets = bookmaker.get('markets', [])
                    if not markets:
                        continue
                    
                    outcomes = markets[0].get('outcomes', [])
                    if len(outcomes) < 3:
                        continue

                    odds_map = {out['name']: out['price'] for out in outcomes}
                    h = odds_map.get(home_team)
                    d = odds_map.get('Draw')
                    a = odds_map.get(away_team)

                    if h and d and a:
                        # Skip extreme/dead odds outlier checks per book
                        if h > 15.0 or d > 15.0 or a > 15.0 or h < 1.08 or a < 1.08:
                            continue

                        # Calculate individual book's raw margin
                        margin = (1/h + 1/d + 1/a)
                        
                        # Strip margin (De-vig) to find true probability
                        home_probs.append((1/h) / margin * 100)
                        draw_probs.append((1/d) / margin * 100)
                        away_probs.append((1/a) / margin * 100)
                        sharp_count += 1

            # Fallback: If no strict sharp bookmaker is found, average all available books
            if not home_probs:
                for bookmaker in bookmakers:
                    markets = bookmaker.get('markets', [])
                    if not markets: continue
                    outcomes = markets[0].get('outcomes', [])
                    if len(outcomes) < 3: continue
                    odds_map = {out['name']: out['price'] for out in outcomes}
                    h, d, a = odds_map.get(home_team), odds_map.get('Draw'), odds_map.get(away_team)
                    if h and d and a and h < 15.0 and a < 15.0:
                        margin = (1/h + 1/d + 1/a)
                        home_probs.append((1/h) / margin * 100)
                        draw_probs.append((1/d) / margin * 100)
                        away_probs.append((1/a) / margin * 100)
                        sharp_count += 1

            if not home_probs:
                continue

            # Galton Consensus Averages (Mean across sharp sample)
            p_home = sum(home_probs) / len(home_probs)
            p_draw = sum(draw_probs) / len(draw_probs)
            p_away = sum(away_probs) / len(away_probs)

            # ---------------------------------------------------------
            # SHIFT DETECTION & ALERT LOGIC
            # ---------------------------------------------------------
            if match_id in previous_state:
                prev = previous_state[match_id]
                delta_home = p_home - prev['home']
                delta_draw = p_draw - prev['draw']
                delta_away = p_away - prev['away']

                if abs(delta_home) >= DELTA_THRESHOLD or abs(delta_away) >= DELTA_THRESHOLD:
                    msg = (
                        f"🧠 <b>GALTON SHARP CONSENSUS SHIFT</b>\n"
                        f"🏆 League: {league}\n"
                        f"🎯 Sharp Sample: {sharp_count} Bookmakers\n\n"
                        f"⚽ Match: {home_team} vs {away_team}\n\n"
                        f"🏠 {home_team}:\n"
                        f"  • Prob: {prev['home']:.1f}% ➔ {p_home:.1f}%\n"
                        f"  • Delta: {delta_home:+.1f}% {'🟢' if delta_home > 0 else '🔴'}\n\n"
                        f"🤝 Draw:\n"
                        f"  • Prob: {prev['draw']:.1f}% ➔ {p_draw:.1f}%\n"
                        f"  • Delta: {delta_draw:+.1f}% {'🟢' if delta_draw > 0 else '🔴'}\n\n"
                        f"✈️ {away_team}:\n"
                        f"  • Prob: {prev['away']:.1f}% ➔ {p_away:.1f}%\n"
                        f"  • Delta: {delta_away:+.1f}% {'🟢' if delta_away > 0 else '🔴'}"
                    )
                    send_telegram_alert(msg)

            # Update saved consensus state
            previous_state[match_id] = {
                'home': p_home,
                'draw': p_draw,
                'away': p_away
            }

    except Exception as e:
        print(f"Error fetching odds data: {e}")


if __name__ == "__main__":
    print("Galton Sharp Engine active: monitoring sharp probability consensus...")
    send_telegram_alert("🚀 <b>Galton Sharp Engine Active</b>\nMonitoring consensus sharp probability shifts.")
    
    while True:
        fetch_and_process_odds()
        time.sleep(CHECK_INTERVAL)
            
