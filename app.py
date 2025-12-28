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
# TELEGRAM MESAJ FORMAT
# =========================
def format_signal_message(s):
    lines = [f"📊 {s.get('symbol', '?')}"]
    lines.append(f"Fiyat: {s.get('current_price', '-')}")
    lines.append(f"Güç Skoru: {s.get('strength', 0)}/10")
    lines.append(f"Trend: {s.get('ema_trend', '-')}")
    lines.append(f"RSI 1H: {s.get('rsi_1h', '-')}")
    lines.append(f"RSI 4H: {s.get('rsi_4h', '-')}")
    lines.append(f"Direnç 1H: {s.get('resistance_1h', '-')}")
    lines.append(f"Direnç 4H: {s.get('resistance_4h', '-')}")
    
    algos = ", ".join(s.get("algorithms", []))
    if algos:
        lines.append(f"Sinyal Türü: {algos}")
    
    added_algos = s.get("added_algorithms", [])
    if added_algos:
        lines.append(f"⚡ Güçlenen algoritmalar: {', '.join(added_algos)}")
    
    if s.get("success"):
        lines.append("🏆 BAŞARILI SİNYAL")
    
    return "\n".join(lines)

# =========================
# DAILY SUCCESS SUMMARY
# =========================
def daily_success_summary():
    """
    Günlük başarılı sinyalleri döndürür.
    """
    global SUCCESS_SIGNALS
    if SUCCESS_SIGNALS:
        return {"success_signals": SUCCESS_SIGNALS.copy()}
    return None

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
                json={
                    "chat_id": cid,
                    "text": message
                },
                timeout=5
            )
        except Exception as e:
            log(f"Telegram hata: {e}")

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

            raw_data = fetch_bist_data()
            # TR saati timestamp olarak sakla
            LAST_SCAN_TS = int(now.timestamp())
            log(f"Taranan hisse: {len(raw_data)}")

            all_signals = []

            for item in raw_data:
                try:
                    signals = process_signals(item, market_open=market_open())
                    if signals:
                        for s in signals:
                            s["timestamp"] = now.strftime("%H:%M:%S")
                        all_signals.extend(signals)
                except Exception as e:
                    log(f"Sinyal hata {item.get('symbol')}: {e}")

            log(f"Üretilen sinyal: {len(all_signals)}")

            # ⏰ Günlük reset (09:40)
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

            # =========================
            # DASHBOARD HAFIZASI
            # =========================
            for meta in all_signals:
                key = meta["symbol"]
                existing = next(
                    (x for x in persistent_signals if x["symbol"] == key),
                    None
                )

                if existing:
                    if meta.get("strength", 0) > existing.get("strength", 0):
                        existing.update(meta)
                else:
                    persistent_signals.insert(0, meta)

            # =========================
            # TELEGRAM SEND
            # =========================
            if market_open():
                grouped = defaultdict(list)
                for meta in all_signals:
                    grouped[meta["symbol"]].append(meta)

                now_ts = int(time.time())

                for symbol, metas in grouped.items():
                    for meta in metas:
                        key = (symbol, meta.get("type"))
                        prev = sent_signal_cache.get(key, {"strength": 0, "time": 0})

                        send_allowed = (
                            meta.get("strength", 0) > prev["strength"] or
                            now_ts - prev["time"] > REPEAT_DELAY
                        )

                        if send_allowed:
                            telegram_send(format_signal_message(meta))
                            sent_signal_cache[key] = {
                                "strength": meta.get("strength", 0),
                                "time": now_ts
                            }

            # =========================
            # GLOBAL API DATA
            # =========================
            with data_lock:
                LATEST_DATA = raw_data
                LATEST_SIGNALS = persistent_signals.copy()

            # =========================
            # DAILY SUCCESS
            # =========================
            summary = daily_success_summary()
            if summary and summary.get("success_signals"):
                for s in summary["success_signals"]:
                    if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
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
            "last_scan": to_tr_timezone(datetime.fromtimestamp(LAST_SCAN_TS)).strftime("%H:%M:%S"),
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
