
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
from signal_engine import process_signals
from utils import to_tr_timezone

# =========================
# ENV & PATH
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

SUCCESS_STORE_FILE = os.path.join(BASE_DIR, "successful_signals.json")

# =========================
# FLASK APP
# =========================
app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []
SUCCESS_SIGNALS = []

persistent_signals = []
LAST_SCAN_TS = None
SYSTEM_STARTED = False

sent_signal_cache = {}

data_lock = threading.Lock()
DAILY_SENT = {"strong_stocks": False, "summary": False}

REPEAT_DELAY = 15 * 60  # 15 dk

# =========================
# UTILS
# =========================
def log(msg):
    print(f"[APP] {msg}", flush=True)

def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj

# =========================
# SUCCESS STORE
# =========================
def load_success_store():
    global SUCCESS_SIGNALS
    if os.path.exists(SUCCESS_STORE_FILE):
        try:
            with open(SUCCESS_STORE_FILE, "r", encoding="utf-8") as f:
                SUCCESS_SIGNALS = json.load(f)
        except Exception:
            SUCCESS_SIGNALS = []
    else:
        SUCCESS_SIGNALS = []

def save_success_store():
    try:
        with open(SUCCESS_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(SUCCESS_SIGNALS, f, ensure_ascii=False)
    except Exception as e:
        log(f"Başarı kaydetme hatası: {e}")

def reset_success_store():
    global SUCCESS_SIGNALS, persistent_signals
    SUCCESS_SIGNALS = []
    persistent_signals = []
    save_success_store()

# =========================
# MARKET TIME
# =========================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# =========================
# TELEGRAM
# =========================
def telegram_send(message):
    if not TELEGRAM_TOKEN or not CHAT_IDS or not message:
        return

    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": message},
                timeout=5
            )
        except Exception as e:
            log(f"Telegram hata: {e}")

# =========================
# BACKGROUND LOOP
# =========================
def background_loop():
    global LATEST_DATA, LATEST_SIGNALS, LAST_SCAN_TS
    global SYSTEM_STARTED, sent_signal_cache, persistent_signals

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    log("Bot başlatıldı")

    load_success_store()
    last_reset_date = None

    while True:
        try:
            now = to_tr_timezone(datetime.now(timezone.utc))
            LAST_SCAN_TS = int(now.timestamp())

            # 🚨 KRİTİK DÜZELTME
            if not market_open():
                time.sleep(60)
                continue

            raw_data = fetch_bist_data()
            all_signals = []

            for item in raw_data:
                try:
                    signals = process_signals(item, market_open=True)
                    if signals:
                        for s in signals:
                            s["timestamp"] = now.strftime("%H:%M:%S")
                        all_signals.extend(signals)
                except Exception as e:
                    log(f"Sinyal hata {item.get('symbol')}: {e}")

            # 09:40 reset
            if (
                now.weekday() < 5 and
                last_reset_date != now.date() and
                now.time() >= dtime(9, 40)
            ):
                last_reset_date = now.date()
                reset_success_store()
                sent_signal_cache = {}
                DAILY_SENT["strong_stocks"] = False
                DAILY_SENT["summary"] = False

            # Dashboard hafızası
            for meta in all_signals:
                key = meta["symbol"]
                existing = next((x for x in persistent_signals if x["symbol"] == key), None)
                if existing:
                    if meta.get("strength", 0) > existing.get("strength", 0):
                        existing.update(meta)
                else:
                    persistent_signals.insert(0, meta)

            # Telegram
            grouped = defaultdict(list)
            for meta in all_signals:
                grouped[meta["symbol"]].append(meta)

            now_ts = int(time.time())
            for symbol, metas in grouped.items():
                for meta in metas:
                    key = (symbol, meta.get("type"))
                    prev = sent_signal_cache.get(key, {"strength": 0, "time": 0})
                    if (
                        meta.get("strength", 0) > prev["strength"] or
                        now_ts - prev["time"] > REPEAT_DELAY
                    ):
                        telegram_send(meta.get("symbol"))
                        sent_signal_cache[key] = {
                            "strength": meta.get("strength", 0),
                            "time": now_ts
                        }

            with data_lock:
                LATEST_DATA = raw_data
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
    with data_lock:
        last_scan_time = None
        if LAST_SCAN_TS:
            dt_utc = datetime.fromtimestamp(LAST_SCAN_TS, tz=timezone.utc)
            dt_tr = to_tr_timezone(dt_utc)
            last_scan_time = dt_tr.strftime("%Y-%m-%d %H:%M:%S")

        return jsonify(make_json_safe({
            "system_active": SYSTEM_STARTED,
            "market_open": market_open(),
            "last_scan": last_scan_time,
            "signals": LATEST_SIGNALS,
            "success_signals": SUCCESS_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False
    )
