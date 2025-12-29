import os
import time
import json
import threading
import requests
from datetime import datetime, timezone, time as dtime
from collections import defaultdict
from copy import deepcopy

from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

from utils import (
    to_tr_timezone,
    get_fallback_symbols,
    fetch_yf_ohlcv,
    calculate_rsi_ema
)

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

persistent_signals = []   # dashboard hafızası
LAST_SCAN_TS = 0
SYSTEM_STARTED = False

sent_signal_cache = {}    # telegram tekrar kontrolü

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
# HIBRIT SİNYAL & LEVEL-UP
# =========================
def is_strong_signal(s):
    if not isinstance(s, dict):
        return False
    if s.get("strength", 0) < 5:
        return False
    algos = s.get("algorithms", [])
    combined = s.get("combined_algorithms", [])
    if "super_kombine" in algos or "kombine" in algos or "l2" in algos or "l3" in algos or "order_block" in algos:
        return True
    if combined:
        return True
    return False

def format_signal_message(meta):
    """Telegram mesaj formatı"""
    msg = f"{meta.get('symbol')} - {meta.get('action','')} | Güç Skoru: {meta.get('strength',0)}\n"
    msg += f"Fiyat: {meta.get('current_price','-')}\n"
    msg += f"Algoritmalar: {','.join(meta.get('algorithms',[]))}"
    return msg

# =========================
# FETCH & PROCESS
# =========================
def fetch_and_process():
    symbols = get_fallback_symbols()
    results = []
    now = to_tr_timezone(datetime.now(timezone.utc))

    for sym in symbols:
        try:
            # YahooFinance OHLCV
            ohlcv = fetch_yf_ohlcv(sym)
            rsi_ema_data = calculate_rsi_ema(ohlcv)
            
            # Güçlü AL mantığı
            strength = 0
            algos = []
            action = ""
            if rsi_ema_data["signal"]:
                strength = rsi_ema_data["strength"]
                algos = rsi_ema_data["algorithms"]
                action = "GÜÇLÜ AL"

            results.append({
                "symbol": sym,
                "current_price": ohlcv["close"][-1],
                "timestamp": now.strftime("%H:%M:%S"),
                "strength": strength,
                "algorithms": algos,
                "action": action,
                "rsi_1h": rsi_ema_data["rsi_1h"],
                "rsi_4h": rsi_ema_data["rsi_4h"],
                "ema_trend": rsi_ema_data["ema_trend"],
                "first_signal_time": now.strftime("%H:%M:%S") if strength>0 else None,
            })
        except Exception as e:
            log(f"{sym} işlenemedi: {e}")

    return results

# =========================
# BACKGROUND LOOP
# =========================
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
            raw_data = fetch_and_process()
            LAST_SCAN_TS = int(time.time())
            log(f"Taranan hisse: {len(raw_data)}")

            all_signals = raw_data

            # Günlük reset
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
                log("09:40 reset yapıldı")

            # DASHBOARD HAFIZASI
            for meta in all_signals:
                key = meta["symbol"]
                existing = next((x for x in persistent_signals if x["symbol"]==key), None)
                if existing:
                    if meta.get("strength",0) > existing.get("strength",0):
                        meta["level_change"]="GÜÇLENEN ⚡"
                        meta["strengthen_time"]=now.strftime("%H:%M:%S")
                        existing.update(meta)
                else:
                    persistent_signals.insert(0, meta)

            # TELEGRAM GÖNDERİMİ
            if market_open():
                now_ts = int(time.time())
                for meta in all_signals:
                    key = (meta["symbol"], meta.get("type"))
                    prev = sent_signal_cache.get(key, {"strength":0,"time":0})
                    send_allowed = meta.get("strength",0)>prev["strength"] or now_ts-prev["time"]>REPEAT_DELAY
                    if send_allowed:
                        telegram_send(format_signal_message(meta))
                        sent_signal_cache[key]={"strength":meta.get("strength",0),"time":now_ts}

            # GLOBAL API DATA
            with data_lock:
                LATEST_DATA = raw_data
                LATEST_SIGNALS = deepcopy(persistent_signals)

            # DAILY SUCCESS
            for s in all_signals:
                if s.get("strength",0)>=7 and not any(x["symbol"]==s["symbol"] for x in SUCCESS_SIGNALS):
                    SUCCESS_SIGNALS.append(s)
                    save_success_store()

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
        return jsonify(make_json_safe({
            "system_active": SYSTEM_STARTED,
            "market_open": market_open(),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS,
            "success_signals": SUCCESS_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static","dashboard.html")

# =========================
# MAIN
# =========================
if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=False,use_reloader=False)
