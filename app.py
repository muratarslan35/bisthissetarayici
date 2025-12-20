import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory

from fetch_bist import fetch_bist_data
from signal_engine import safe_process_bist_data, scan_strong_stocks, daily_success_summary
from utils import to_tr_timezone
from dotenv import load_dotenv

# ==================================================
# ENV
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# ==================================================
# FLASK
# ==================================================
app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []   # 🔥 DASHBOARD SİNYAL HAVUZU
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
data_lock = threading.Lock()

# ==================================================
# TELEGRAM
# ==================================================
def telegram_send(msg):
    if not TELEGRAM_TOKEN or not CHAT_IDS:
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

# ==================================================
# MARKET HOURS
# ==================================================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        (now.hour > 9 or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# ==================================================
# BACKGROUND LOOP
# ==================================================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED, LATEST_SIGNALS
    SYSTEM_STARTED = True

    telegram_send("🤖 BIST BOT AKTİF")

    while True:
        try:
            raw_data = fetch_bist_data()

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            # ------------------ PİYASA AÇIK ------------------
            if market_open():
                signals = safe_process_bist_data(raw_data, market_open=True)

                dashboard_signals = []
                for sid, msg, meta in signals:
                    telegram_send(msg)

                    # 🔥 DASHBOARD FORMAT
                    dashboard_signals.append({
                        "symbol": meta.get("symbol"),
                        "signal_type": meta.get("type"),
                        "current_price": meta.get("price"),
                        "rsi": meta.get("rsi"),
                        "time": to_tr_timezone(datetime.now(timezone.utc)).strftime("%H:%M:%S"),
                        "details": meta
                    })

                with data_lock:
                    LATEST_SIGNALS = dashboard_signals

            # ------------------ PİYASA KAPALI ------------------
            else:
                strong = scan_strong_stocks(raw_data)
                if strong:
                    telegram_send(
                        "📌 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" +
                        "\n".join(strong)
                    )

                summary = daily_success_summary()
                if summary:
                    telegram_send(summary)

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

# ==================================================
# THREAD
# ==================================================
threading.Thread(target=background_loop, daemon=True).start()

# ==================================================
# API
# ==================================================
@app.route("/api")
def api():
    with data_lock:
        return jsonify({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "data": LATEST_DATA,          # ham tarama
            "signals": LATEST_SIGNALS     # 🔥 GERÇEK SİNYALLER
        })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
