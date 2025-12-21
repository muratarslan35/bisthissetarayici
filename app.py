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
LATEST_SIGNALS = []          # 🔥 Dashboard sinyalleri
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
TEST_MODE = False            # ✅ TEST KORUMA FLAG
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

    telegram_send("🤖 BIST SİNYAL BOTU AKTİF")

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

                    dashboard_signals.append({
                        "symbol": meta.get("symbol"),
                        "price": meta.get("price"),
                        "type": meta.get("type"),
                        "title": meta.get("title", meta.get("type")),
                        "direction": meta.get("direction", "up"),
                        "trend_strength": meta.get("trend_strength", 50),
                        "support": meta.get("support"),
                        "resistance": meta.get("resistance"),

                        # --- geriye dönük uyum (SİLİNMEDİ)
                        "signal_type": meta.get("type"),
                        "current_price": meta.get("price"),
                        "rsi": meta.get("rsi"),
                        "time": to_tr_timezone(datetime.now(timezone.utc)).strftime("%H:%M:%S"),
                        "details": meta
                    })

                # ✅ TEST MODU AÇIKSA EZME
                with data_lock:
                    if not TEST_MODE:
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
# TEST SIGNAL (EZİLMEZ)
# ==================================================
@app.route("/api/test_signal")
def test_signal():
    global TEST_MODE

    TEST_MODE = True  # 🔥 background loop sinyal ezemez

    test_meta = {
        "symbol": "TESTHISSE",
        "type": "strong_reversal",
        "title": "🧪 TEST – Güçlü Dönüş (L2)",
        "direction": "up",
        "trend_strength": 82,
        "support": 120.0,
        "resistance": 135.0,
        "price": 123.45,
        "rsi": 49.8,
        "level": "L2",
        "target_hit": False
    }

    test_signal = {
        "symbol": "TESTHISSE",
        "price": 123.45,
        "type": "strong_reversal",
        "title": "🧪 TEST – Güçlü Dönüş (L2)",
        "direction": "up",
        "trend_strength": 82,
        "support": 120.0,
        "resistance": 135.0,
        "signal_type": "strong_reversal",
        "current_price": 123.45,
        "rsi": 49.8,
        "time": to_tr_timezone(datetime.now(timezone.utc)).strftime("%H:%M:%S"),
        "details": test_meta
    }

    with data_lock:
        LATEST_SIGNALS.insert(0, test_signal)

    telegram_send(
        "🧪 TEST SİNYALİ\n\n"
        "Hisse: TESTHISSE\n"
        "📈 Güçlü Dönüş (L2)\n"
        "Fiyat: 123.45\n"
        "Trend Gücü: %82\n"
        "RSI: 49.8"
    )

    return jsonify({"ok": 1, "msg": "Test sinyali üretildi"})

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
            "data": LATEST_DATA,
            "signals": LATEST_SIGNALS
        })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
