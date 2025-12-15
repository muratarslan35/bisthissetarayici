# app.py
import os
import threading
import time
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone

app = Flask(__name__)

# ================= GLOBAL STATE =================
LATEST_DATA = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = 0
data_lock = threading.Lock()

sent_signals = {}
last_reset_date = None

# ================= ENV =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# ================= TELEGRAM =================
def telegram_send(text):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in CHAT_IDS:
        try:
            requests.post(url, json={"chat_id": cid, "text": text}, timeout=5)
        except:
            pass

# ================= MARKET STATUS =================
def market_open_status():
    now = to_tr_timezone(datetime.now(timezone.utc))
    if now.weekday() >= 5:
        return 0
    if (now.hour > 9 or (now.hour == 9 and now.minute >= 55)) and now.hour < 18:
        return 1
    return 0

# ================= 09:50 RESET =================
def check_daily_reset():
    global sent_signals, last_reset_date
    now_tr = to_tr_timezone(datetime.now(timezone.utc))
    today = now_tr.date()

    if (now_tr.hour > 9) or (now_tr.hour == 9 and now_tr.minute >= 50):
        if last_reset_date != today:
            sent_signals = {}
            last_reset_date = today
            telegram_send("🔄 09:50 reset – yeni gün taraması başladı")

# ================= BACKGROUND LOOP =================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED
    SYSTEM_STARTED = 1
    telegram_send("🤖 Sistem başlatıldı – Oracle VM üzerinde aktif")

    while True:
        try:
            check_daily_reset()
            data = fetch_bist_data()

            with data_lock:
                LATEST_DATA = data
                LAST_SCAN_TS = int(time.time())

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

# ================= START THREAD IMMEDIATELY =================
threading.Thread(target=background_loop, daemon=True).start()

# ================= API =================
@app.route("/api")
def api():
    with data_lock:
        return jsonify({
            "system_active": SYSTEM_STARTED,
            "market_open": market_open_status(),
            "last_scan": LAST_SCAN_TS,
            "data": LATEST_DATA
        })

# ================= WAKE =================
@app.route("/wake")
def wake():
    return jsonify({"ok": 1, "message": "Sistem zaten aktif"})

# ================= DASHBOARD =================
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ================= MAIN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
