import os
import time
import threading
import requests
import telebot

TELEGRAM_BOT_TOKEN = "8968074202:AAHBTAt9-K1p-vgxB4SJbSdJEzUTRtoSMz0"
TELEGRAM_CHAT_ID =  "8367160484"
ODDS_API_KEY = "ce18a6d60e07f56d00d8e3860db124d3"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
market_cache = {}


def devig(h, d, a):
    """Calculates true zero-vig probability and fair dividend odds."""
    if h <= 0 or d <= 0 or a <= 0:
        return 0, (0, 0, 0), (0, 0, 0)
    margin = (1 / h + 1 / d + 1 / a) * 100
    p_h = (1 / h) / (margin / 100) * 100
    p_d = (1 / d) / (margin / 100) * 100
    p_a = (1 / a) / (margin / 100) * 100
    
    div_h = 100 / p_h if p_h > 0 else 0
    div_d = 100 / p_d if p_d > 0 else 0
    div_a = 100 / p_a if p_a > 0 else 0

    return margin, (p_h, p_d, p_a), (div_h, div_d, div_a)


def fetch_multibookie_consensus(query_name):
    """Searches live global bookies for the match and calculates Galton's Crowd Consensus."""
    if not ODDS_API_KEY:
        return None

    # Search upcoming soccer matches globally
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={ODDS_API_KEY}&regions=eu,uk,us&markets=h2h"
    try:
        res = requests.get(url)
        if res.status_code == 200:
            matches = res.json()
            query = query_name.lower()
            
            for m in matches:
                home = m.get("home_team", "")
                away = m.get("away_team", "")
                full_fixture = f"{home} vs {away}".lower()
                
                # Check if match matches user input
                if query in full_fixture or any(part in full_fixture for part in query.split()):
                    bookmakers = m.get("bookmakers", [])
                    if not bookmakers:
                        continue

                    h_list, d_list, a_list = [], [], []
                    for b in bookmakers:
                        for market in b.get("markets", []):
                            if market.get("key") == "h2h":
                                for outcome in market.get("outcomes", []):
                                    if outcome.get("name") == home:
                                        h_list.append(outcome.get("price"))
                                    elif outcome.get("name") == away:
                                        a_list.append(outcome.get("price"))
                                    else:
                                        d_list.append(outcome.get("price"))

                    if h_list and d_list and a_list:
                        avg_h = sum(h_list) / len(h_list)
                        avg_d = sum(d_list) / len(d_list)
                        avg_a = sum(a_list) / len(a_list)
                        
                        margin, (ph, pd, pa), (divh, divd, diva) = devig(avg_h, avg_d, avg_a)
                        
                        return {
                            "home": home,
                            "away": away,
                            "bookie_count": len(bookmakers),
                            "avg_odds": (avg_h, avg_d, avg_a),
                            "crowd_margin": margin,
                            "crowd_prob": (ph, pd, pa),
                            "crowd_div": (divh, divd, diva)
                        }
    except Exception as e:
        print(f"Error querying crowd consensus: {e}")
    return None


# --- GALTON WISDOM OF CROWD COMMAND ---
@bot.message_handler(commands=['galton'])
def handle_galton(message):
    """
    Format: /galton [OpenH] [OpenD] [OpenA] [CurrH] [CurrD] [CurrA] [Team A vs Team B]
    Example: /galton 2.10 3.30 3.20 2.15 3.40 2.90 Limache vs Nublense
    """
    try:
        raw_args = message.text.split()[1:]
        if len(raw_args) < 7:
            bot.reply_to(
                message,
                "⚠️ <b>Usage Format:</b>\n"
                "<code>/galton [OpenH] [OpenD] [OpenA] [CurrH] [CurrD] [CurrA] [Match Title]</code>\n\n"
                "<i>Example:</i>\n"
                "<code>/galton 2.10 3.30 3.20 2.15 3.40 2.90 Limache vs Nublense</code>",
                parse_mode="HTML"
            )
            return

        h_o, d_o, a_o, h_c, d_c, a_c = map(float, raw_args[:6])
        match_title = " ".join(raw_args[6:])

        # 1. Process Input Movement (e.g., Bet365)
        m_o, (po_h, po_d, po_a), (div_o_h, div_o_d, div_o_a) = devig(h_o, d_o, a_o)
        m_c, (pc_h, pc_d, pc_a), (div_c_h, div_c_d, div_c_a) = devig(h_c, d_c, a_c)

        dh_raw = ((1/h_c) - (1/h_o)) * 100
        dd_raw = ((1/d_c) - (1/d_o)) * 100
        da_raw = ((1/a_c) - (1/a_o)) * 100

        dh_true = pc_h - po_h
        dd_true = pc_d - po_d
        da_true = pc_a - po_a

        # 2. Query Global Multi-Bookie Crowd Consensus
        crowd_data = fetch_multibookie_consensus(match_title)

        # 3. Build Detailed Diagnostic Report
        report = (
            f"🧠 <b>GALTON WISDOM-OF-THE-CROWD ENGINE</b>\n"
            f"⚽ <b>{match_title.upper()}</b>\n"
            f"───────────────\n"
            f"📌 <b>INPUT MOVEMENT ANALYSIS (e.g. Bet365)</b>\n"
            f"• <b>Margin:</b> {m_o:.1f}% ➔ {m_c:.1f}% ({m_c - m_o:+.1f}%)\n\n"

            f"🏠 <b>HOME:</b>\n"
            f"  • Odds: {h_o:.2f} ➔ <b>{h_c:.2f}</b>\n"
            f"  • Implied (Raw): {100/h_o:.1f}% ➔ {100/h_c:.1f}% ({dh_raw:+.1f}%)\n"
            f"  • True Fair Prob: {po_h:.1f}% ➔ <b>{pc_h:.1f}%</b> ({dh_true:+.1f}% {'🟢' if dh_true > 0 else '🔴'})\n"
            f"  • Fair Dividend: {div_o_h:.2f} ➔ <b>{div_c_h:.2f}</b>\n\n"

            f"🤝 <b>DRAW:</b>\n"
            f"  • Odds: {d_o:.2f} ➔ <b>{d_c:.2f}</b>\n"
            f"  • Implied (Raw): {100/d_o:.1f}% ➔ {100/d_c:.1f}% ({dd_raw:+.1f}%)\n"
            f"  • True Fair Prob: {po_d:.1f}% ➔ <b>{pc_d:.1f}%</b> ({dd_true:+.1f}% {'🟢' if dd_true > 0 else '🔴'})\n"
            f"  • Fair Dividend: {div_o_d:.2f} ➔ <b>{div_c_d:.2f}</b>\n\n"

            f"✈️ <b>AWAY:</b>\n"
            f"  • Odds: {a_o:.2f} ➔ <b>{a_c:.2f}</b>\n"
            f"  • Implied (Raw): {100/a_o:.1f}% ➔ {100/a_c:.1f}% ({da_raw:+.1f}%)\n"
            f"  • True Fair Prob: {po_a:.1f}% ➔ <b>{pc_a:.1f}%</b> ({da_true:+.1f}% {'🟢' if da_true > 0 else '🔴'})\n"
            f"  • Fair Dividend: {div_o_a:.2f} ➔ <b>{div_c_a:.2f}</b>\n"
            f"───────────────\n"
        )

        if crowd_data:
            c_h, c_d, c_a = crowd_data["crowd_prob"]
            div_h, div_d, div_a = crowd_data["crowd_div"]
            report += (
                f"🌐 <b>GLOBAL CROWD CONSENSUS ({crowd_data['bookie_count']} Bookies)</b>\n"
                f"• <b>Crowd Margin:</b> {crowd_data['crowd_margin']:.1f}%\n"
                f"• <b>True Crowd Prob:</b> H {c_h:.1f}% | D {c_d:.1f}% | A {c_a:.1f}%\n"
                f"• <b>True Fair Dividends:</b> H <b>{div_h:.2f}</b> | D <b>{div_a:.2f}</b> | A <b>{div_a:.2f}</b>\n"
            )
        else:
            report += "🌐 <i>Global multi-bookie live consensus line not active for this fixture. Showing de-vigged input diagnostic.</i>"

        bot.reply_to(message, report, parse_mode="HTML")

    except ValueError:
        bot.reply_to(message, "❌ Check your odds inputs. Make sure numbers are valid (e.g. 2.10 3.30 3.20 2.15 3.40 2.90).")
    except Exception as e:
        bot.reply_to(message, f"❌ Diagnostic error: {e}")


# --- START TELEGRAM LISTENER ---
print("Galton Wisdom Engine ready...")
bot.infinity_polling()
    
