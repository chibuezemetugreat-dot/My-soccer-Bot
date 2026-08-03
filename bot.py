import os
import time
import requests
import telebot

# Grab secrets from environment variables
TELEGRAM_BOT_TOKEN = "8968074202:AAHBTAt9-K1p-vgxB4SJbSdJEzUTRtoSMz0"
TELEGRAM_CHAT_ID = "8367160484"
ODDS_API_KEY = "ce18a6d60e07f56d00d8e3860db124d3"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Store market state to track odds shifts over time
market_cache = {}


def calculate_devig(h, d, a):
    """Calculates margin and de-vigged true fair probabilities."""
    margin = (1 / h + 1 / d + 1 / a) * 100
    p_h = (1 / h) / (margin / 100) * 100
    p_d = (1 / d) / (margin / 100) * 100
    p_a = (1 / a) / (margin / 100) * 100
    return margin, p_h, p_d, p_a


# --- COMMAND 1: MANUAL GALTON DIAGNOSTIC ---
@bot.message_handler(commands=['galton'])
def handle_galton(message):
    """
    Usage: /galton [OpenH] [OpenD] [OpenA] [CurrH] [CurrD] [CurrA]
    Example: /galton 2.50 3.20 2.70 2.15 3.20 3.30
    """
    try:
        args = message.text.split()[1:]
        if len(args) != 6:
            bot.reply_to(
                message,
                "⚠️ <b>Usage Format:</b>\n<code>/galton [OpenH] [OpenD] [OpenA] [CurrH] [CurrD] [CurrA]</code>\n\n<i>Example:</i> <code>/galton 2.50 3.20 2.70 2.15 3.20 3.30</code>",
                parse_mode="HTML"
            )
            return

        h_o, d_o, a_o, h_c, d_c, a_c = map(float, args)

        margin_o, po_h, po_d, po_a = calculate_devig(h_o, d_o, a_o)
        margin_c, pc_h, pc_d, pc_a = calculate_devig(h_c, d_c, a_c)

        dh = pc_h - po_h
        dd = pc_d - po_d
        da = pc_a - po_a
        d_margin = margin_c - margin_o

        report = (
            f"📊 <b>ON-DEMAND GALTON DIAGNOSTIC</b>\n"
            f"───────────────\n"
            f"🏠 <b>Home:</b>\n"
            f"  • Odds: {h_o:.2f} ➔ {h_c:.2f}\n"
            f"  • True Prob: {po_h:.1f}% ➔ {pc_h:.1f}%\n"
            f"  • Delta: {dh:+.1f}% {'🟢' if dh > 0 else '🔴'}\n\n"
            f"🤝 <b>Draw:</b>\n"
            f"  • Odds: {d_o:.2f} ➔ {d_c:.2f}\n"
            f"  • True Prob: {po_d:.1f}% ➔ {pc_d:.1f}%\n"
            f"  • Delta: {dd:+.1f}% {'🟢' if dd > 0 else '🔴'}\n\n"
            f"✈️ <b>Away:</b>\n"
            f"  • Odds: {a_o:.2f} ➔ {a_c:.2f}\n"
            f"  • True Prob: {po_a:.1f}% ➔ {pc_a:.1f}%\n"
            f"  • Delta: {da:+.1f}% {'🟢' if da > 0 else '🔴'}\n\n"
            f"📈 <b>Margin:</b> {margin_o:.1f}% ➔ {margin_c:.1f}% ({d_margin:+.1f}%)\n"
        )
        bot.reply_to(message, report, parse_mode="HTML")

    except ValueError:
        bot.reply_to(message, "❌ Invalid numbers provided. Space out your odds numbers correctly.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error executing calculation: {e}")


# --- AUTOMATED SHARP MARKET TRACKER (THE ODDS API) ---
def fetch_live_odds():
    """Fetches upcoming soccer odds across multiple sportsbooks from The Odds API."""
    if not ODDS_API_KEY:
        print("No ODDS_API_KEY environment variable provided.")
        return

    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=eu,uk&markets=h2h"
    try:
        res = requests.get(url)
        if res.status_code == 200:
            data = res.json()
            for match in data:
                match_id = match.get("id")
                home_team = match.get("home_team")
                away_team = match.get("away_team")

                # Average odds across available bookmakers
                bookmakers = match.get("bookmakers", [])
                if not bookmakers:
                    continue

                h_odds, d_odds, a_odds = [], [], []
                for b in bookmakers:
                    for m in b.get("markets", []):
                        if m.get("key") == "h2h":
                            for outcome in m.get("outcomes", []):
                                if outcome.get("name") == home_team:
                                    h_odds.append(outcome.get("price"))
                                elif outcome.get("name") == away_team:
                                    a_odds.append(outcome.get("price"))
                                else:
                                    d_odds.append(outcome.get("price"))

                if h_odds and d_odds and a_odds:
                    avg_h = sum(h_odds) / len(h_odds)
                    avg_d = sum(d_odds) / len(d_odds)
                    avg_a = sum(a_odds) / len(a_odds)

                    margin, p_h, p_d, p_a = calculate_devig(avg_h, avg_d, avg_a)

                    # Check for probability shift vs cached baseline
                    if match_id in market_cache:
                        prev = market_cache[match_id]
                        diff_h = p_h - prev['p_h']
                        
                        # Send alert if Home true probability shifts by >= 3%
                        if abs(diff_h) >= 3.0:
                            alert_text = (
                                f"🚨 <b>SHARP MARKET SHIFT DETECTED</b>\n"
                                f"⚽ <b>{home_team} vs {away_team}</b>\n"
                                f"───────────────\n"
                                f"🏠 <b>{home_team}:</b> {prev['p_h']:.1f}% ➔ {p_h:.1f}% ({diff_h:+.1f}%)\n"
                                f"📊 Average Sharp Market Odds: {avg_h:.2f} | {avg_d:.2f} | {avg_a:.2f}"
                            )
                            bot.send_message(TELEGRAM_CHAT_ID, alert_text, parse_mode="HTML")

                    # Update cache
                    market_cache[match_id] = {'p_h': p_h, 'p_d': p_d, 'p_a': p_a}

        else:
            print(f"Odds API Error: {res.status_code}")
    except Exception as e:
        print(f"Fetch error: {e}")


# Send startup message
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    try:
        bot.send_message(
            TELEGRAM_CHAT_ID,
            "🚀 <b>Galton Engine Online!</b>\n"
            "• Watching Sharp Bookmakers for live shifts 24/7.\n"
            "• Type <code>/galton [Odds]</code> anytime for manual diagnostics.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Startup message failed: {e}")

# Start non-blocking polling so /galton commands respond instantly
import threading

def poll_telegram():
    bot.infinity_polling()

threading.Thread(target=poll_telegram, daemon=True).start()

# Main loop for fetching Odds API data every 5 minutes
print("Galton engine & Telegram listener running...")
while True:
    fetch_live_odds()
    time.sleep(300)  # Wait 5 minutes between API checks
        
