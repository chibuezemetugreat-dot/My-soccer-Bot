import sqlite3
import time
import requests

# ==========================================
# 🔑 1. YOUR CREDENTIALS & CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = "8680294291:AAE2kV7LIL_5ET3t6iz5wl8C1LKzBKrqpkM"
TELEGRAM_CHAT_ID = "8367160484"
ODDS_API_KEY = "ce18a6d60e07f56d00d8e3860db124d3"

# Setting this to "upcoming" scans ALL active soccer leagues globally
SPORT_KEY = "upcoming"

# THRESHOLD: Alert if any outcome's probability shifts by 2.0% or more
DELTA_THRESHOLD = 2.0


# ==========================================
# 🗄️ 2. DATABASE INITIALIZATION
# ==========================================
def init_db():
    conn = sqlite3.connect("odds_history.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            match_id TEXT PRIMARY KEY,
            sport_title TEXT,
            home_team TEXT,
            away_team TEXT,
            prob_h REAL,
            prob_d REAL,
            prob_a REAL,
            margin REAL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


# ==========================================
# 📩 3. TELEGRAM SENDER
# ==========================================
def send_telegram_alert(message_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")


# ==========================================
# 📊 4. GLOBAL SCANNER & PROBABILITY SHIFT CALCULATOR
# ==========================================
def scan_and_detect_deltas():
    print("🔍 Fetching live odds for global soccer matches...")

    api_url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }

    response = requests.get(api_url, params=params)
    if response.status_code != 200:
        print(f"API Error: {response.status_code}")
        return

    matches = response.json()
    conn = sqlite3.connect("odds_history.db")
    cursor = conn.cursor()

    for match in matches:
        # FILTER: Only process soccer leagues
        sport_name = match.get('sport_key', '')
        if "soccer" not in sport_name:
            continue

        league_title = match.get('sport_title', 'Soccer')
        match_id = match.get('id')
        home_team = match.get('home_team')
        away_team = match.get('away_team')
        bookmakers = match.get('bookmakers', [])

        if not bookmakers:
            continue

        outcomes = bookmakers[0]['markets'][0]['outcomes']
        odds_dict = {item['name']: item['price'] for item in outcomes}

        h_odds = odds_dict.get(home_team)
        a_odds = odds_dict.get(away_team)
        d_odds = odds_dict.get('Draw')

        if not (h_odds and a_odds and d_odds):
            continue

        # 1. Calculate raw implied probabilities from decimal odds
        raw_h, raw_d, raw_a = 1/h_odds, 1/d_odds, 1/a_odds

        # 2. Calculate house overround margin
        curr_margin = (raw_h + raw_d + raw_a) * 100

        # 3. Scale implied probabilities to true 100% distribution
        curr_prob_h = (raw_h / (curr_margin / 100)) * 100
        curr_prob_d = (raw_d / (curr_margin / 100)) * 100
        curr_prob_a = (raw_a / (curr_margin / 100)) * 100

        # Check local database for historical baseline
        cursor.execute("SELECT prob_h, prob_d, prob_a, margin FROM odds_snapshots WHERE match_id = ?", (match_id,))
        previous_snapshot = cursor.fetchone()

        if previous_snapshot is None:
            # Match seen for the first time: Store initial baseline snapshot
            cursor.execute('''
                INSERT INTO odds_snapshots (match_id, sport_title, home_team, away_team, prob_h, prob_d, prob_a, margin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (match_id, league_title, home_team, away_team, curr_prob_h, curr_prob_d, curr_prob_a, curr_margin))
            conn.commit()
            print(f"📌 Saved baseline [{league_title}]: {home_team} vs {away_team}")
        else:
            old_h, old_d, old_a, old_margin = previous_snapshot

            # Calculate Probability Deltas (Added or Deducted)
            delta_h = curr_prob_h - old_h
            delta_d = curr_prob_d - old_d
            delta_a = curr_prob_a - old_a
            delta_margin = curr_margin - old_margin

            # Trigger condition: Did any probability or margin shift past threshold?
            if abs(delta_h) >= DELTA_THRESHOLD or abs(delta_d) >= DELTA_THRESHOLD or abs(delta_a) >= DELTA_THRESHOLD:

                # Format add (+) or deduct (-) delta strings
                h_sign = f"+{delta_h:.1f}% 🟢" if delta_h > 0 else f"{delta_h:.1f}% 🔴"
                d_sign = f"+{delta_d:.1f}% 🟢" if delta_d > 0 else f"{delta_d:.1f}% 🔴"
                a_sign = f"+{delta_a:.1f}% 🟢" if delta_a > 0 else f"{delta_a:.1f}% 🔴"

                alert_text = (
                    f"⚡ *GLOBAL PROBABILITY SHIFT DETECTED*\n"
                    f"🏆 *League:* `{league_title}`\n\n"
                    f"⚽ *Match:* {home_team} vs {away_team}\n"
                    f"📊 *Margin:* `{old_margin:.1f}%` ➔ `{curr_margin:.1f}%` ({delta_margin:+.1f}%)\n\n"
                    f"🏠 *{home_team}:*\n"
                    f"  • Prob: `{old_h:.1f}%` ➔ `{curr_prob_h:.1f}%`\n"
                    f"  • Delta: `{h_sign}`\n\n"
                    f"🤝 *Draw:*\n"
                    f"  • Prob: `{old_d:.1f}%` ➔ `{curr_prob_d:.1f}%`\n"
                    f"  • Delta: `{d_sign}`\n\n"
                    f"✈️ *{away_team}:*\n"
                    f"  • Prob: `{old_a:.1f}%` ➔ `{curr_prob_a:.1f}%`\n"
                    f"  • Delta: `{a_sign}`\n\n"
                    f"🎯 *New Odds:* H `{h_odds}` | D `{d_odds}` | A `{a_odds}`"
                )

                send_telegram_alert(alert_text)
                print(f"🚨 SHIFT ALERT SENT [{league_title}]: {home_team} vs {away_team}")

                # Update snapshot so future shifts are compared against this new value
                cursor.execute('''
                    UPDATE odds_snapshots
                    SET prob_h = ?, prob_d = ?, prob_a = ?, margin = ?
                    WHERE match_id = ?
                ''', (curr_prob_h, curr_prob_d, curr_prob_a, curr_margin, match_id))
                conn.commit()

    conn.close()


# ==========================================
# ⏱️ 5. AUTOMATED LOOP (RUNS EVERY 30 MINUTES)
# ==========================================
if __name__ == "__main__":
    init_db()
    print("🚀 Global Soccer Shift Tracker Online!")
    send_telegram_alert("🤖 *Shift Tracker Active:* Monitoring global soccer probability movements!")

    while True:
        scan_and_detect_deltas()
        time.sleep(1800)  # Waits 30 minutes between scans
