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

# ================== GLOBALS ==================
LATEST_DATA = {"status": "init", "data": None, "timestamp": None}
data_lock = threading.Lock()

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

sent_signals = {}
last_reset_date = None

SYSTEM_STATE = {
    "running": False,
    "sleeping": False,
    "last_loop": None
}

wake_event = threading.Event()

# ================== JSON SAFE ==================
def json_safe(obj):
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj

# ================== TELEGRAM ==================
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
            }, timeout=8)
        except:
            pass

# ================== 09:50 RESET ==================
def check_daily_reset():
    global sent_signals, last_reset_date
    now_tr = to_tr_timezone(datetime.now(timezone.utc))
    today = now_tr.date()

    if now_tr.hour == 9 and now_tr.minute >= 50:
        if last_reset_date != today:
            sent_signals = {}
            last_reset_date = today
            app.logger.info("🔄 09:50 reset yapıldı")

# ================== MARKET OPEN ==================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    if now.weekday() >= 5:
        return False
    return (now.hour > 9 or (now.hour == 9 and now.minute >= 40)) and now.hour < 18

# ================== LOOP ==================
def update_loop():
    SYSTEM_STATE["running"] = True
    telegram_send("🤖 Sistem aktif – tarama başladı")

    while True:
        SYSTEM_STATE["last_loop"] = int(time.time())

        if not market_open():
            SYSTEM_STATE["sleeping"] = True
            wake_event.wait(timeout=300)
            wake_event.clear()
            continue

        SYSTEM_STATE["sleeping"] = False
        check_daily_reset()

        try:
            data = fetch_bist_data()
            with data_lock:
                LATEST_DATA.update({
                    "status": "ok",
                    "timestamp": int(time.time()),
                    "data": data
                })
        except Exception as e:
            app.logger.error(e)

        time.sleep(60)

# ================== START ONCE ==================
threading.Thread(target=update_loop, daemon=True).start()
start_self_ping()

# ================== ROUTES ==================
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

@app.route("/api")
def api():
    with data_lock:
        return jsonify(json_safe({
            "system": SYSTEM_STATE,
            "market_open": market_open(),
            "data": LATEST_DATA
        }))

@app.route("/wake", methods=["POST"])
def wake():
    wake_event.set()
    SYSTEM_STATE["sleeping"] = False
    return jsonify({"status": "ok", "message": "Sistem uyandırıldı"})
