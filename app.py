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

# ==================================================
# ENV
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# ==================================================
# TELEGRAM STATE
# ==================================================
TELEGRAM_ENABLED = True
TELEGRAM_FAIL_COUNT = 0
TELEGRAM_MAX_FAIL = 3
LAST_TELEGRAM_CHECK = 0
TELEGRAM_RETRY_INTERVAL = 300  # 5 dk

# ==================================================
# FLASK
# ==================================================
app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False

data_lock = threading.Lock()

# ==================================================
# DAILY FLAGS
# ==================================================
DAILY_SENT = {"strong_stocks": False, "summary": False}
LAST_DAY = None

# ==================================================
# JSON SAFE
# ==================================================
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(i) for i in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj

# ==================================================
# TELEGRAM CHECK
# ==================================================
def telegram_healthcheck():
    global TELEGRAM_ENABLED, TELEGRAM_FAIL_COUNT, LAST_TELEGRAM_CHECK

    now = time.time()
    if now - LAST_TELEGRAM_CHECK < TELEGRAM_RETRY_INTERVAL:
        return

    LAST_TELEGRAM_CHECK = now

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
            timeout=5
        )
        if r.status_code == 200:
            TELEGRAM_ENABLED = True
            TELEGRAM_FAIL_COUNT = 0
            print("✅ Telegram tekrar aktif")
    except Exception:
        pass

# ==================================================
# TELEGRAM SEND
# ==================================================
def telegram_send(msg):
    global TELEGRAM_ENABLED, TELEGRAM_FAIL_COUNT

    if not TELEGRAM_TOKEN or not CHAT_IDS or not msg:
        return

    if not TELEGRAM_ENABLED:
        telegram_healthcheck()
        return

    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=5
            )
            TELEGRAM_FAIL_COUNT = 0
        except Exception as e:
            TELEGRAM_FAIL_COUNT += 1
            print(f"Telegram gönderilemedi {cid}: {e}")

            if TELEGRAM_FAIL_COUNT >= TELEGRAM_MAX_FAIL:
                TELEGRAM_ENABLED = False
                print("⚠️ Telegram devre dışı bırakıldı")

# ==================================================
# MARKET HOURS
# ==================================================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# ==================================================
# BACKGROUND LOOP
# ==================================================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED, LATEST_SIGNALS, DAILY_SENT, LAST_DAY

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLADI")

    while True:
        try:
            raw_data = fetch_bist_data()

            now = to_tr_timezone(datetime.now(timezone.utc))
            today = now.date()

            if LAST_DAY != today:
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                LAST_DAY = today

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            if market_open():
                signals = safe_process_bist_data(raw_data, market_open=True)

                grouped = defaultdict(list)
                for s in signals:
                    if s.get("symbol"):
                        grouped[s["symbol"]].append(s)

                for symbol, algs in grouped.items():
                    telegram_send(format_signal_message(symbol, algs))

                dashboard = []
                seen = set()

                for meta in signals:
                    sym = meta.get("symbol")
                    if not sym or sym in seen:
                        continue
                    seen.add(sym)

                    dashboard.append({
                        "symbol": sym,
                        "price": meta.get("price") or meta.get("current_price"),
                        "type": meta.get("type"),
                        "direction": meta.get("direction", "up"),
                        "strength": meta.get("trend_strength", 50),
                        "support": meta.get("support"),
                        "resistance": meta.get("resistance"),
                        "rsi": meta.get("rsi"),
                        "time": now.strftime("%H:%M:%S"),
                        "details": meta
                    })

                with data_lock:
                    LATEST_SIGNALS = dashboard

            else:
                if not DAILY_SENT["strong_stocks"]:
                    strong = scan_strong_stocks(raw_data)
                    if strong:
                        telegram_send("📌 GÜÇLÜ HİSSELER\n\n" + "\n".join(strong))
                    DAILY_SENT["strong_stocks"] = True

                if not DAILY_SENT["summary"]:
                    summary = daily_success_summary(include_details=True)
                    if summary:
                        telegram_send(
                            f"📊 GÜN SONU\nBaşarı: {summary['hit']}/{summary['total']} "
                            f"(%{summary['success_rate']:.2f})"
                        )
                    DAILY_SENT["summary"] = True

                if fallback_daily_update_if_needed(raw_data):
                    msg = fallback_daily_report_message()
                    if msg:
                        telegram_send(msg)

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
        return jsonify(make_json_safe({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "telegram_status": "active" if TELEGRAM_ENABLED else "offline",
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
