import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory

from fetch_bist import fetch_bist_data
from signal_engine import safe_process_bist_data
from utils import to_tr_timezone

from dotenv import load_dotenv

# ==================================================
# ENV (KALICI YÜKLEME)
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
LAST_SCAN_TS = 0
SYSTEM_STARTED = False

data_lock = threading.Lock()

# ==================================================
# JSON SAFE HELPER  (🔥 KRİTİK FIX)
# ==================================================
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, (bool, int, float, str)) or obj is None:
        return obj
    try:
        return obj.item()
    except Exception:
        return str(obj)

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
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED

    SYSTEM_STARTED = True

    telegram_send(
        "🤖 BIST BOT AKTİF\n"
        "• Oracle VM\n"
        "• Dashboard + Telegram senkron\n"
        f"• Başlangıç: {to_tr_timezone(datetime.now(timezone.utc)).strftime('%H:%M:%S')}"
    )

    first_open_scan_done = False

    while True:
        try:
            raw_data = fetch_bist_data()

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            # --------- SABAH AÇILIŞ MESAJI ---------
            if market_open() and not first_open_scan_done:
                first_open_scan_done = True
                telegram_send(
                    f"📈 PİYASA AÇILDI\n"
                    f"Taranan hisse sayısı: {len(raw_data)}\n"
                    f"İlk tarama tamamlandı"
                )

            # --------- SİNYAL MOTORU ---------
            signals = safe_process_bist_data(raw_data)

            for _, msg, _ in signals:
                telegram_send(msg)

            # --------- PİYASA KAPALI ÖZET ---------
            if not market_open():
                strong = [x["symbol"] for x in raw_data if x.get("super_combined_ok")]
                if strong:
                    telegram_send(
                        "📊 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" +
                        "\n".join(f"• {s}" for s in strong[:5])
                    )

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

# ==================================================
# THREAD START
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
            "data": make_json_safe(LATEST_DATA)
        })

@app.route("/wake")
def wake():
    return jsonify({"ok": 1})

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
