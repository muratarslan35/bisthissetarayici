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
from fallback_manager import (
    fallback_daily_update_if_needed,
    fallback_daily_report_message
)

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
LAST_RESET_DATE = None

DAILY_SENT = {"strong_stocks": False, "summary": False}
sent_signal_cache = {}

data_lock = threading.Lock()


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
    global LATEST_DATA, LATEST_SIGNALS, LAST_SCAN_TS, SYSTEM_STARTED
    global DAILY_SENT, sent_signal_cache

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    log("Bot başlatıldı")

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

            # DASHBOARD HER ZAMAN GÜNCELLENİR
            seen = set()
            dashboard_payload = []
            for meta in all_signals:
                if meta["symbol"] not in seen:
                    seen.add(meta["symbol"])
                    dashboard_payload.append(meta)

            with data_lock:
                LATEST_DATA = raw_data
                LATEST_SIGNALS = dashboard_payload

            # TELEGRAM SADECE MARKET AÇIKKEN
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

            # GÜNLÜK BAŞARI
            summary = daily_success_summary()
            if summary:
                for s in summary.get("success_signals", []):
                    if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
                        SUCCESS_SIGNALS.append(s)

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
