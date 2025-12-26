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

LAST_SCAN_TS = 0
SYSTEM_STARTED = False
sent_signal_cache = {}

data_lock = threading.Lock()
DAILY_SENT = {"strong_stocks": False, "summary": False}

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
    global SUCCESS_SIGNALS
    SUCCESS_SIGNALS = []
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

def should_daily_reset(now):
    # Günlük sıfırlama saat 09:50
    reset_time = dtime(9, 50)
    if now.time() >= reset_time:
        return True
    return False

def background_loop():
    global LATEST_DATA, LATEST_SIGNALS, LAST_SCAN_TS, SYSTEM_STARTED, sent_signal_cache

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
                        all_signals.extend(signals)
                except Exception as e:
                    log(f"Sinyal hata {item.get('symbol')}: {e}")

            log(f"Üretilen sinyal: {len(all_signals)}")

            # Günlük reset kontrolü
            if last_reset_date != now.date() and should_daily_reset(now):
                last_reset_date = now.date()
                reset_success_store()
                sent_signal_cache = {}
                DAILY_SENT["strong_stocks"] = False
                DAILY_SENT["summary"] = False
                log("Günlük başarı sinyalleri sıfırlandı")

            # Dashboard payload: tüm alanlar default ile
            seen = set()
            dashboard_payload = []
            for meta in all_signals:
                if meta["symbol"] not in seen:
                    seen.add(meta["symbol"])
                    safe_meta = {
                        "symbol": meta.get("symbol", "-"),
                        "current_price": meta.get("current_price", 0),
                        "ema_trend": meta.get("ema_trend", "➖"),
                        "rsi": meta.get("rsi", 0),
                        "rsi_1h": meta.get("rsi_1h", 0),
                        "rsi_4h": meta.get("rsi_4h", 0),
                        "rsi_1h_synthetic": meta.get("rsi_1h_synthetic", 0),
                        "rsi_4h_synthetic": meta.get("rsi_4h_synthetic", 0),
                        "volume_tag": meta.get("volume_tag", "-"),
                        "support_15m": meta.get("support_15m", "-"),
                        "support_1h": meta.get("support_1h", "-"),
                        "support_4h": meta.get("support_4h", "-"),
                        "support_1d": meta.get("support_1d", "-"),
                        "resistance_15m": meta.get("resistance_15m", "-"),
                        "resistance_1h": meta.get("resistance_1h", "-"),
                        "resistance_4h": meta.get("resistance_4h", "-"),
                        "resistance_1d": meta.get("resistance_1d", "-"),
                        "action": meta.get("action", "-"),
                        "success": meta.get("success", False),
                        "volume_badge": meta.get("volume_badge", None),
                        "combined_algorithms": meta.get("combined_algorithms", [])
                    }
                    dashboard_payload.append(safe_meta)

            with data_lock:
                LATEST_DATA = raw_data
                LATEST_SIGNALS = dashboard_payload

            # Telegram: sadece market açıkken
            if market_open():
                grouped = defaultdict(list)
                for meta in all_signals:
                    grouped[meta["symbol"]].append(meta)

                for symbol, metas in grouped.items():
                    for meta in metas:
                        key = (symbol, meta["type"])
                        prev = sent_signal_cache.get(key, {}).get("strength", 0)
                        curr = meta.get("strength", 0)
                        strong = curr > prev

                        telegram_send(format_signal_message(meta), strong)
                        sent_signal_cache[key] = {
                            "strength": curr,
                            "time": now.isoformat()
                        }

            # Günlük başarılı sinyallerin kaydı
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
