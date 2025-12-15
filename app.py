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
LATEST_DATA = []
LAST_SCAN_TS = None
SYSTEM_ACTIVE = False

data_lock = threading.Lock()

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
                "text": text
            }, timeout=5)
        except:
            pass

# ================= MARKET STATUS =================
def is_market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    if now.weekday() >= 5:
        return False
    return (now.hour > 9 or (now.hour == 9 and now.minute >= 55)) and now.hour < 18

# ================= BACKGROUND LOOP =================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_ACTIVE

    SYSTEM_ACTIVE = True
    telegram_send("🤖 Sistem aktif – tarama başladı")

    while True:
        try:
            if is_market_open():
                data = fetch_bist_data()

                # 🔒 JSON SAFE
                safe_data = []
                for d in data:
                    safe_data.append({
                        k: (bool(v) if isinstance(v, (bool,)) else v)
                        for k, v in d.items()
                    })

                with data_lock:
                    LATEST_DATA = safe_data
                    LAST_SCAN_TS = int(time.time())

        except Exception as e:
            print("SCAN ERROR:", e)

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
    now = int(time.time())
    with data_lock:
        return jsonify({
            "system_active": bool(SYSTEM_ACTIVE),
            "scan_active": bool(LAST_SCAN_TS and (now - LAST_SCAN_TS) < 180),
            "market_open": bool(is_market_open()),
            "last_scan": LAST_SCAN_TS,
            "data": LATEST_DATA
        })

# ================= WAKE =================
@app.route("/wake")
def wake():
    global LAST_SCAN_TS
    LAST_SCAN_TS = int(time.time())
    return jsonify({"ok": True})

# ================= DASHBOARD =================
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")
