# app.py
import os
import time
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone
from self_ping import start_self_ping

app = Flask(__name__)

LATEST_DATA = {
    "status": "init",
    "data": [],
    "timestamp": None
}

sent_signals = {}
last_reset_date = None

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# ---------------- TELEGRAM ----------------
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

# ---------------- 09:50 RESET ----------------
def check_daily_reset():
    global sent_signals, last_reset_date
    now_tr = to_tr_timezone(datetime.now(timezone.utc))
    today = now_tr.date()

    if now_tr.hour > 9 or (now_tr.hour == 9 and now_tr.minute >= 50):
        if last_reset_date != today:
            sent_signals = {}
            last_reset_date = today
            telegram_send("🔄 09:50 reset – yeni gün taraması başladı")

# ---------------- API ----------------
@app.route("/api")
def api():
    global LATEST_DATA

    check_daily_reset()

    try:
        data = fetch_bist_data()
        LATEST_DATA = {
            "status": "ok",
            "data": data,
            "timestamp": int(time.time())
        }
    except Exception as e:
        LATEST_DATA["status"] = "error"

    return jsonify(LATEST_DATA)

# ---------------- DASHBOARD ----------------
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ---------------- WAKE ----------------
@app.route("/wake")
def wake():
    return jsonify({
        "ok": True,
        "message": "Sistem uyandırıldı, tarama /api ile tetiklenecek"
    })
