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

DAILY_SENT = {
    "strong_stocks": False,
    "summary": False
}

sent_signal_cache = {}

data_lock = threading.Lock()


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
    except Exception:
        pass


def reset_success_store():
    global SUCCESS_SIGNALS
    SUCCESS_SIGNALS = []
    save_success_store()


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
        except Exception:
            pass


def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )


def should_daily_reset(now):
    global LAST_RESET_DATE
    reset_time = dtime(9, 50)
    if now.time() >= reset_time and LAST_RESET_DATE != now.date():
        LAST_RESET_DATE = now.date()
        return True
    return False


def background_loop():
    global LATEST_DATA, LATEST_SIGNALS, LAST_SCAN_TS, SYSTEM_STARTED
    global DAILY_SENT, sent_signal_cache

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    load_success_store()

    while True:
        try:
            now = to_tr_timezone(datetime.now(timezone.utc))
            raw_data = fetch_bist_data()

            if should_daily_reset(now):
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                sent_signal_cache = {}
                reset_success_store()

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            all_signals = []

            if market_open():
                for item in raw_data:
                    signals = process_signals(item, market_open=True)
                    if signals:
                        all_signals.extend(signals)

                grouped = defaultdict(list)
                for meta in all_signals:
                    grouped[meta["symbol"]].append(meta)

                for symbol, metas in grouped.items():
                    for meta in metas:
                        key = (symbol, meta["type"])
                        prev = sent_signal_cache.get(key, {}).get("strength", 0)
                        curr = meta.get("strength", 0)
                        strong = curr > prev

                        telegram_send(
                            format_signal_message(meta),
                            strong_increase=strong
                        )

                        sent_signal_cache[key] = {
                            "strength": curr,
                            "time": now.isoformat()
                        }

                seen = set()
                dashboard_payload = []
                for meta in all_signals:
                    if meta["symbol"] not in seen:
                        seen.add(meta["symbol"])
                        dashboard_payload.append(meta)

                with data_lock:
                    LATEST_SIGNALS = dashboard_payload

                summary = daily_success_summary()
                if summary:
                    for s in summary.get("success_signals", []):
                        if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
                            SUCCESS_SIGNALS.append(s)
                            save_success_store()

            else:
                if not DAILY_SENT["strong_stocks"]:
                    strong_list = []
                    for item in raw_data:
                        r = scan_strong_stocks(item)
                        if r:
                            strong_list.extend(r)

                    if strong_list:
                        telegram_send(
                            "📌 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" +
                            "\n\n".join(format_signal_message(s) for s in strong_list)
                        )
                    DAILY_SENT["strong_stocks"] = True

                if not DAILY_SENT["summary"]:
                    summary = daily_success_summary()
                    if summary and summary.get("success_signals"):
                        lines = ["📊 GÜNLÜK BAŞARILI SİNYALLER"]
                        for s in summary["success_signals"]:
                            lines.append(f"{s['symbol']} | {s['algorithm']} | {s['time']}")
                        telegram_send("\n".join(lines))
                    DAILY_SENT["summary"] = True

                if fallback_daily_update_if_needed(raw_data):
                    msg = fallback_daily_report_message()
                    if msg:
                        telegram_send(msg)

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)


threading.Thread(target=background_loop, daemon=True).start()


@app.route("/api")
def api():
    with data_lock:
        return jsonify(make_json_safe({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS,
            "success_signals": SUCCESS_SIGNALS
        }))


@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
