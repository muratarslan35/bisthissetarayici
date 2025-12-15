# app.py
import os
import threading
import time
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone
from self_ping import start_self_ping

app = Flask(__name__)

# ================= GLOBAL STATE =================
LATEST_DATA = {
    "status": "init",
    "data": [],
    "timestamp": None
}

LAST_SCAN_TS = None
SYSTEM_STARTED = False
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
            requests.post(url, json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=5)
        except:
            pass

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

    SYSTEM_STARTED = True
    telegram_send("🤖 Sistem başlatıldı – arka plan taraması aktif")

    while True:
        try:
            check_daily_reset()
            data = fetch_bist_data()

            with data_lock:
                LATEST_DATA = {
                    "status": "ok",
                    "data": data,
                    "timestamp": int(time.time())
                }
                LAST_SCAN_TS = int(time.time())

        except Exception as e:
            with data_lock:
                LATEST_DATA["status"] = "error"

        time.sleep(60)

# ================= START ONCE =================
_started = False
@app.before_request
def start_once():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=background_loop, daemon=True).start()
        start_self_ping()

# ================= API =================
@app.route("/api")
def api():
    with data_lock:
        return jsonify({
            "system_active": SYSTEM_STARTED,
            "status": LATEST_DATA["status"],
            "data": LATEST_DATA["data"],
            "timestamp": LATEST_DATA["timestamp"],
            "last_scan": LAST_SCAN_TS
        })

# ================= WAKE =================
@app.route("/wake")
def wake():
    global LAST_SCAN_TS
    LAST_SCAN_TS = int(time.time())
    return jsonify({
        "ok": True,
        "message": "Sistem uyandırıldı (mevcut tarama devam ediyor)"
    })

# ================= DASHBOARD =================
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")
