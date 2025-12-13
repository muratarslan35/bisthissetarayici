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

# ---------------- GLOBALS ----------------
LATEST_DATA = {"status": "init", "data": [], "timestamp": None}
data_lock = threading.Lock()

TELEGRAM_TOKEN = "8588829956:AAEK2-wa75CoHQPjPFEAUU_LElRBduC-_TU"
CHAT_IDS = [661794787]

SENT_SIGNALS = {}
LAST_RESET_DATE = None
SENT_LOCK = threading.Lock()

# ---------------- TELEGRAM ----------------
def telegram_send(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in CHAT_IDS:
        try:
            payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=6)
        except Exception as e:
            print("[TELEGRAM ERROR]", e)

# ---------------- RESET LOGIC ----------------
def should_reset_sent_signals(now_tr, last_reset_date):
    if last_reset_date is None:
        return True
    if now_tr.date() > last_reset_date:
        return now_tr.hour >= 9
    return False

# ---------------- SIGNAL PROCESS ----------------
def process_and_notify(data_list):
    global LAST_RESET_DATE

    now_tr = to_tr_timezone(datetime.now(timezone.utc))

    with SENT_LOCK:
        if should_reset_sent_signals(now_tr, LAST_RESET_DATE):
            SENT_SIGNALS.clear()
            LAST_RESET_DATE = now_tr.date()
            print("[APP] SENT_SIGNALS reset at 09:00 TR")

    for item in data_list:
        symbol = item.get("symbol")
        if not symbol:
            continue

        with SENT_LOCK:
            sent = SENT_SIGNALS.setdefault(symbol, set())

        signals = item.get("signals", [])
        for sig in signals:
            sig_key = sig["key"]
            if sig_key in sent:
                continue

            telegram_send(sig["message"])

            with SENT_LOCK:
                sent.add(sig_key)

# ---------------- BACKGROUND LOOP ----------------
def update_loop():
    print("[APP] update_loop started")
    telegram_send("🤖 Sistem aktif – BIST tarama başladı")

    while True:
        try:
            data = fetch_bist_data()

            with data_lock:
                LATEST_DATA = {
                    "status": "ok",
                    "timestamp": int(time.time()),
                    "data": data
                }

            process_and_notify(data)

        except Exception as e:
            print("[APP ERROR]", e)

        time.sleep(60)

# ---------------- START THREAD ONCE ----------------
_started = False
@app.before_request
def start_bg():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=update_loop, daemon=True).start()
        start_self_ping()
        print("[APP] Background started")

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return send_from_directory("static", "dashboard.html")

@app.route("/latest-data")
def latest_data():
    with data_lock:
        return jsonify(LATEST_DATA)
