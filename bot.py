import os
import time
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
API_KEY = os.getenv("ce18a6d60e07f56d00d8e3860db124d3")
TELEGRAM_BOT_TOKEN = os.getenv("8680294291:AAE2kV7LIL_5ET3t6iz5wl8C1LKzBKrqpkM")
TELEGRAM_CHAT_ID = os.getenv("8367160484")

# Check threshold parameters
DELTA_THRESHOLD = 5.0  # Alert if probability shifts by 5% or more
CHECK_INTERVAL = 300   # Check every 5 minutes (300 seconds)

# Store previous odds to detect shifts: {match_id: {selection: probability}}
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
    """Fetches odds, filters live/extreme games, and tracks sharp probability moves."""
    global previous_state
    
    if not API_KEY:
        print("ODDS_API_KEY environment variable is missing.")
        return

    # Odds API Endpoint for Soccer Matches
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY}&regions=eu,uk&markets=h2h"
    
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

            # ---------------------------------------------------------
            # 🛑 FILTER 1: Skip Live / Finished Games (Pre-match only)
            # ---------------------------------------------------------
            if commence_time_str:
                commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                if commence_time <= now:
                    continue  # Game already started, skip!

            # Grab bookmakers
            bookmakers = event.get('bookmakers', [])
            if not bookmakers:
                continue

            # Get odds from the first available bookmaker (e.g., Pinnacle/365)
            outcomes = bookmakers[0].get('markets', [{}])[0].get('outcomes', [])
            if len(outcomes) < 3:
                continue

            # Extract prices (H2H)
            odds_map = {out['name']: out['price'] for out in outcomes}
            home_odds = odds_map.get(home_team)
            away_odds = odds_map.get(away_team)
            draw_odds = odds_map.get('Draw')

            if not home_odds or not away_odds or not draw_odds:
                continue

            # ---------------------------------------------------------
            # 🛑 FILTER 2: Skip Extreme / Dead Odds
            # ---------------------------------------------------------
            if home_odds > 15.0 or draw_odds > 15.0 or away_odds > 15.0:
                continue
            if home_odds < 1.10 or away_odds < 1.10:
                continue

            # Calculate raw margin and implied probabilities
            raw_margin = (1/home_odds + 1/draw_odds + 1/away_odds) * 100
            p_home = (1 / home_odds) / (raw_margin / 100) * 100
            p_draw = (1 / draw_odds) / (raw_margin / 100) * 100
            p_away = (1 / away_odds) / (raw_margin / 100) * 100

            # ---------------------------------------------------------
            # SHIFT DETECTION & ALERT LOGIC
            # ---------------------------------------------------------
            if match_id in previous_state:
                prev = previous_state[match_id]
                delta_home = p_home - prev['home']
                delta_draw = p_draw - prev['draw']
                delta_away = p_away - prev['away']

                # Trigger alert if any selection shifts beyond threshold
                if abs(delta_home) >= DELTA_THRESHOLD or abs(delta_away) >= DELTA_THRESHOLD:
                    msg = (
                        f"⚡ <b>GLOBAL PROBABILITY SHIFT DETECTED</b>\n"
                        f"🏆 League: {league}\n\n"
                        f"⚽ Match: {home_team} vs {away_team}\n"
                        f"📊 Margin: {prev['margin']:.1f}% ➔ {raw_margin:.1f}%\n\n"
                        f"🏠 {home_team}:\n"
                        f"  • Prob: {prev['home']:.1f}% ➔ {p_home:.1f}%\n"
                        f"  • Delta: {delta_home:+.1f}% {'🟢' if delta_home > 0 else '🔴'}\n\n"
                        f"🤝 Draw:\n"
                        f"  • Prob: {prev['draw']:.1f}% ➔ {p_draw:.1f}%\n"
                        f"  • Delta: {delta_draw:+.1f}% {'🟢' if delta_draw > 0 else '🔴'}\n\n"
                        f"✈️ {away_team}:\n"
                        f"  • Prob: {prev['away']:.1f}% ➔ {p_away:.1f}%\n"
                        f"  • Delta: {delta_away:+.1f}% {'🟢' if delta_away > 0 else '🔴'}\n\n"
                        f"🎯 New Odds: H {home_odds} | D {draw_odds} | A {away_odds}"
                    )
                    send_telegram_alert(msg)

            # Update saved state
            previous_state[match_id] = {
                'home': p_home,
                'draw': p_draw,
                'away': p_away,
                'margin': raw_margin
            }

    except Exception as e:
        print(f"Error fetching odds data: {e}")


if __name__ == "__main__":
    print("Shift tracker active: monitoring global soccer probability movement (Pre-match mode)...")
    send_telegram_alert("🚀 <b>Soccer Shift Tracker Active</b>\nMonitoring pre-match probability shifts.")
    
    while True:
        fetch_and_process_odds()
        time.sleep(CHECK_INTERVAL)
        
