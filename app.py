import os
import time
import threading
import requests
from datetime import datetime, timezone
from collections import defaultdict

from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

from fetch_bist import fetch_bist_data
from signal_engine import (
    safe_process_bist_data,
    scan_strong_stocks,
    daily_success_summary,
    format_signal_message
)
from utils import to_tr_timezone
from fallback_manager import (
    fallback_daily_update_if_needed,
    fallback_daily_report_message
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

app = Flask(__name__, static_folder="static")

LATEST_SIGNALS = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
data_lock = threading.Lock()

DAILY_SENT = {"strong_stocks": False, "summary": False}
LAST_DAY = None

# ================= TELEGRAM =================
def telegram_send(msg):
    if not TELEGRAM_TOKEN or not CHAT_IDS or not msg:
        return
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=5
            )
        except Exception:
            pass

# ================= MARKET =================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# ================= BACKGROUND =================
def background_loop():
    global SYSTEM_STARTED, LAST_SCAN_TS, LATEST_SIGNALS, DAILY_SENT, LAST_DAY

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU AKTİF")

    while True:
        try:
            raw_data = fetch_bist_data()
            now = to_tr_timezone(datetime.now(timezone.utc))
            today = now.date()

            if LAST_DAY != today:
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                LAST_DAY = today

            if market_open():
                signals = safe_process_bist_data(raw_data, market_open=True)

                grouped = defaultdict(list)
                for s in signals:
                    grouped[s["symbol"]].append(s)

                dashboard = []
                for sym, items in grouped.items():
                    msg = format_signal_message(sym, items)
                    telegram_send(msg)
                    dashboard.append(items[0])

                with data_lock:
                    LATEST_SIGNALS = dashboard
                    LAST_SCAN_TS = int(time.time())

            else:
                if not DAILY_SENT["strong_stocks"]:
                    strong = scan_strong_stocks(raw_data)
                    if strong:
                        telegram_send("📌 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" + "\n".join(strong))
                    DAILY_SENT["strong_stocks"] = True

                if not DAILY_SENT["summary"]:
                    summary = daily_success_summary(include_details=True)
                    if summary:
                        lines = [
                            "📊 GÜN SONU BAŞARI",
                            f"{summary['hit']} / {summary['total']} | %{summary['success_rate']}"
                        ]
                        telegram_send("\n".join(lines))
                    DAILY_SENT["summary"] = True

                if fallback_daily_update_if_needed(raw_data):
                    msg = fallback_daily_report_message()
                    if msg:
                        telegram_send(msg)

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

# ================= ROUTES =================
@app.route("/api")
def api():
    with data_lock:
        return jsonify({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS
        })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=background_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
