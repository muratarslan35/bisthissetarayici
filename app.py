import os
import time
import json
import threading
import requests
from datetime import datetime, timezone, time as dtime
from collections import defaultdict

from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

from fetch_bist import fetch_bist_data
from signal_engine import process_signals, update_success
from utils import to_tr_timezone

# =========================
# ENV
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# =========================
# FLASK
# =========================
app = Flask(__name__)

LATEST_SIGNALS = []
persistent_signals = []
SUCCESS_SENT = set()

SYSTEM_STARTED = False
LAST_SCAN_TS = None
sent_signal_cache = {}

data_lock = threading.Lock()
REPEAT_DELAY = 15 * 60

DAILY_SENT = {
    "summary": False
}

# =========================
# UTILS
# =========================
def log(msg):
    print(f"[APP] {msg}", flush=True)

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
        except:
            pass

def format_signal_message(s):
    return (
        f"📊 {s['symbol']}\n"
        f"Fiyat: {s.get('current_price')}\n"
        f"Güç: {s.get('strength')}\n"
        f"Trend: {s.get('ema_trend')}\n"
        f"Algoritmalar: {', '.join(s.get('algorithms', []))}"
    )

def format_success_message(s):
    return (
        f"🏆 BAŞARILI SİNYAL\n\n"
        f"{s['symbol']}\n"
        f"Giriş: {s['entry']}\n"
        f"Hedef: {s['target']}\n"
        f"Algoritma: {s['algorithm']}"
    )

# =========================
# MARKET
# =========================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# =========================
# BACKGROUND
# =========================
def background_loop():
    global SYSTEM_STARTED, LAST_SCAN_TS, LATEST_SIGNALS

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    log("Bot başlatıldı")

    last_day = None

    while True:
        try:
            now = to_tr_timezone(datetime.now(timezone.utc))
            LAST_SCAN_TS = int(now.timestamp())

            if not market_open():
                time.sleep(60)
                continue

            raw = fetch_bist_data()
            all_signals = []

            for item in raw:
                signals = process_signals(item)
                for s in signals:
                    all_signals.append(s)
                    update_success(s["symbol"], s["current_price"])

            # -------------------------
            # TELEGRAM SİNYALLER
            # -------------------------
            for s in all_signals:
                key = (s["symbol"], s["type"])
                prev = sent_signal_cache.get(key, {"time": 0, "strength": 0})

                if (
                    s["strength"] > prev["strength"] or
                    time.time() - prev["time"] > REPEAT_DELAY
                ):
                    telegram_send(format_signal_message(s))
                    sent_signal_cache[key] = {
                        "time": time.time(),
                        "strength": s["strength"]
                    }

            # -------------------------
            # BAŞARILI SİNYAL
            # -------------------------
            for s in all_signals:
                if s.get("success") and s["symbol"] not in SUCCESS_SENT:
                    telegram_send(format_success_message(s))
                    SUCCESS_SENT.add(s["symbol"])

            # -------------------------
            # GÜNLÜK ÖZET
            # -------------------------
            if now.time() >= dtime(17, 45) and not DAILY_SENT["summary"]:
                total = len(persistent_signals)
                success = len(SUCCESS_SENT)

                telegram_send(
                    f"📊 GÜNLÜK ÖZET\n\n"
                    f"Toplam sinyal: {total}\n"
                    f"Başarılı: {success}"
                )
                DAILY_SENT["summary"] = True

            # Yeni gün reset
            if last_day != now.date():
                last_day = now.date()
                DAILY_SENT["summary"] = False
                SUCCESS_SENT.clear()

            with data_lock:
                for s in all_signals:
                    if s not in persistent_signals:
                        persistent_signals.append(s)
                LATEST_SIGNALS = persistent_signals.copy()

        except Exception as e:
            log(f"SCAN ERROR: {e}")

        time.sleep(60)

# =========================
# THREAD
# =========================
threading.Thread(target=background_loop, daemon=True).start()

# =========================
# API
# =========================
@app.route("/api")
def api():
    return jsonify({
        "system_active": SYSTEM_STARTED,
        "signals": LATEST_SIGNALS
    })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
