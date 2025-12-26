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
from signal_engine import (
    process_signals,
    format_signal_message,
    scan_strong_stocks,
    daily_success_summary
)
from utils import to_tr_timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

SUCCESS_STORE_FILE = os.path.join(BASE_DIR, "successful_signals.json")

app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []
SUCCESS_SIGNALS = []

persistent_signals = []  # Dashboard sinyallerini kalıcı tutacak
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
sent_signal_cache = {}

data_lock = threading.Lock()
DAILY_SENT = {"strong_stocks": False, "summary": False}
REPEAT_DELAY = 15 * 60  # 15 dakika

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
        log(f"Başarı sinyal kaydetme hatası: {e}")

def reset_success_store():
    global SUCCESS_SIGNALS, persistent_signals
    SUCCESS_SIGNALS = []
    persistent_signals = []
    save_success_store()

def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

def telegram_send(message, strong_increase=False):
    if not TELEGRAM_TOKEN or not CHAT_IDS or not message:
        return
    prefix = "⚡️⚡️ GÜÇ ARTIŞI ⚡️⚡️\n" if strong_increase else ""
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": prefix + message},
                timeout=5
            )
        except Exception as e:
            log(f"Telegram hata: {e}")

def background_loop():
    global LATEST_DATA, LATEST_SIGNALS, LAST_SCAN_TS, SYSTEM_STARTED, sent_signal_cache, persistent_signals

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    log("Bot başlatıldı")
    load_success_store()

    last_reset_date = None

    while True:
        try:
            now = to_tr_timezone(datetime.now(timezone.utc))
            raw_data = fetch_bist_data()
            LAST_SCAN_TS = int(time.time())
            log(f"Taranan hisse: {len(raw_data)}")

            all_signals = []
            for item in raw_data:
                try:
                    signals = process_signals(item, market_open=market_open())
                    if signals:
                        # Her sinyale timestamp ekle
                        for s in signals:
                            s["timestamp"] = now.strftime("%H:%M:%S")
                        all_signals.extend(signals)
                except Exception as e:
                    log(f"Sinyal hata {item.get('symbol')}: {e}")

            log(f"Üretilen sinyal: {len(all_signals)}")

            # Hafta içi 09:40 reset
            if now.weekday() < 5 and (last_reset_date != now.date()) and now.time() >= dtime(9,40):
                last_reset_date = now.date()
                reset_success_store()
                sent_signal_cache = {}
                DAILY_SENT["strong_stocks"] = False
                DAILY_SENT["summary"] = False
                log("Hafta içi sabah 09:40 sinyaller sıfırlandı")

            # Dashboard hafızasını güncelle
            for meta in all_signals:
                key = meta["symbol"]
                existing = next((x for x in persistent_signals if x["symbol"] == key), None)
                if existing:
                    # Güçlendiğinde güncelle
                    if meta.get("strength",0) > existing.get("strength",0):
                        existing.update(meta)
                else:
                    persistent_signals.insert(0, meta)  # yeni sinyaller üstte

            # Telegram: market açıkken gönder
            if market_open():
                grouped = defaultdict(list)
                for meta in all_signals:
                    grouped[meta["symbol"]].append(meta)

                now_ts = int(time.time())
                for symbol, metas in grouped.items():
                    for meta in metas:
                        key = (symbol, meta["type"])
                        prev = sent_signal_cache.get(key, {"strength":0,"time":0})
                        strong = False
                        if meta.get("strength",0) > prev["strength"] or now_ts - prev["time"] > REPEAT_DELAY:
                            strong = meta.get("strength",0) > prev["strength"]
                            telegram_send(format_signal_message(meta), strong)
                            sent_signal_cache[key] = {"strength": meta.get("strength",0), "time": now_ts}

            # Dashboard sinyallerini global olarak set et
            with data_lock:
                LATEST_DATA = raw_data
                LATEST_SIGNALS = persistent_signals.copy()

            # Günlük başarılı sinyaller
            summary = daily_success_summary()
            if summary and summary.get("success_signals"):
                for s in summary["success_signals"]:
                    if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
                        SUCCESS_SIGNALS.append(s)
                        save_success_store()

        except Exception as e:
            log(f"SCAN ERROR: {e}")

        time.sleep(60)

threading.Thread(target=background_loop, daemon=True).start()

@app.route("/api")
def api():
    with data_lock:
        return jsonify(make_json_safe({
            "system_active": SYSTEM_STARTED,
            "market_open": market_open(),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS,
            "success_signals": SUCCESS_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
