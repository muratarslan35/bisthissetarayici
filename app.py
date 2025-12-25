import os
import time
import json
import threading
import requests
from datetime import datetime, timezone, time as dtime
from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv
from collections import defaultdict

from fetch_bist import fetch_bist_data
from signal_engine import (
    process_signals,
    scan_strong_stocks,
    daily_success_summary,
    format_signal_message
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
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
SUCCESS_SIGNALS = []

data_lock = threading.Lock()
DAILY_SENT = {"strong_stocks": False, "summary": False}
LAST_RESET_DATE = None
sent_signals = {}  # (symbol, type) -> {"time": ..., "strength": ...}

_prev_1h = {}
_prev_4h = {}

# ----------------- Fonksiyonlar -----------------

def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(i) for i in obj]
    elif hasattr(obj, "item"):
        return obj.item()
    return obj

def load_success_store():
    global SUCCESS_SIGNALS
    if os.path.exists(SUCCESS_STORE_FILE):
        try:
            with open(SUCCESS_STORE_FILE, "r") as f:
                SUCCESS_SIGNALS = json.load(f)
        except Exception:
            SUCCESS_SIGNALS = []
    else:
        SUCCESS_SIGNALS = []

def save_success_store():
    try:
        with open(SUCCESS_STORE_FILE, "w") as f:
            json.dump(SUCCESS_SIGNALS, f, ensure_ascii=False)
    except Exception:
        pass

def reset_success_store():
    global SUCCESS_SIGNALS
    SUCCESS_SIGNALS = []
    save_success_store()

def telegram_send(msg, strong_increase=False):
    if not TELEGRAM_TOKEN or not CHAT_IDS or not msg:
        return
    prefix = "GÜÇ ARTIŞI ⚡️⚡️⚡️\n" if strong_increase else ""
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": prefix + msg},
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
    if now.time() >= reset_time:
        if LAST_RESET_DATE != now.date():
            LAST_RESET_DATE = now.date()
            return True
    return False

# ----------------- Background Loop -----------------

def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED, LATEST_SIGNALS, DAILY_SENT, SUCCESS_SIGNALS, _prev_1h, _prev_4h, sent_signals

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU AKTİF")
    load_success_store()

    while True:
        try:
            raw_data = fetch_bist_data()
            now = to_tr_timezone(datetime.now(timezone.utc))

            if should_daily_reset(now):
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                reset_success_store()
                _prev_1h = {}
                _prev_4h = {}
                sent_signals = {}

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            if market_open():
                signals = []
                for item in raw_data:
                    s = process_signals(item, market_open=True)
                    if s:
                        signals.extend(s)

                grouped = defaultdict(list)
                for meta in signals:
                    sym = meta.get("symbol")
                    if sym:
                        grouped[sym].append(meta)

                for symbol, alg_list in grouped.items():
                    for meta in alg_list:
                        msg = format_signal_message(meta)
                        prev_strength = sent_signals.get((symbol, meta.get("type")), {}).get("strength", 0)
                        current_strength = meta.get("strength", 0)
                        strong_increase = current_strength > prev_strength
                        telegram_send(msg, strong_increase=strong_increase)
                        sent_signals[(symbol, meta.get("type"))] = {"time": datetime.now(), "strength": current_strength}

                dashboard_signals = []
                seen_symbols = set()
                for meta in signals:
                    sym = meta.get("symbol")
                    if sym in seen_symbols:
                        continue
                    seen_symbols.add(sym)
                    dashboard_signals.append({
                        "symbol": sym,
                        "current_price": meta.get("current_price"),
                        "type": meta.get("type"),
                        "rsi": meta.get("rsi"),
                        "ema_trend": meta.get("ema_trend"),
                        "volume": meta.get("volume"),
                        "volume_avg": meta.get("volume_avg"),
                        "volume_tag": meta.get("volume_tag"),
                        "volume_badge": meta.get("volume_badge"),
                        "action": meta.get("action"),
                        "time": meta.get("time"),
                        "combined_algorithms": meta.get("combined_algorithms", []),
                        "success": meta.get("success", False)
                    })

                with data_lock:
                    LATEST_SIGNALS = dashboard_signals

                summary = daily_success_summary()
                if summary:
                    for s in summary.get("success_signals", []):
                        if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
                            SUCCESS_SIGNALS.append(s)
                            save_success_store()

            else:
                if not DAILY_SENT["strong_stocks"]:
                    strong = scan_strong_stocks(raw_data)
                    if strong:
                        strong_msgs = []
                        for sig in strong:
                            if isinstance(sig, dict):
                                strong_msgs.append(format_signal_message(sig))
                            else:
                                strong_msgs.append(str(sig))
                        telegram_send("📌 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" + "\n\n".join(strong_msgs))
                    DAILY_SENT["strong_stocks"] = True

                if not DAILY_SENT["summary"]:
                    summary = daily_success_summary()
                    if summary:
                        success_list = summary.get("success_signals", [])
                        total_signals = len(LATEST_DATA)
                        hit_signals = len(success_list)
                        success_rate = (hit_signals / total_signals * 100) if total_signals else 0
                        lines = [
                            "📊 GÜN SONU BAŞARI ÖZETİ",
                            f"Tarih: {summary['date']}",
                            f"Toplam Başarılı: {hit_signals} / Toplam Sinyal: {total_signals}",
                            f"Başarı Oranı: %{success_rate:.2f}",
                            "",
                            "Başarılı Sinyaller:"
                        ]
                        for s in success_list:
                            lines.append(f"• {s['symbol']} | {s['algorithm']} | Saat: {s['time']} | Fiyat: {s['price']}")
                        telegram_send("\n".join(lines))
                    DAILY_SENT["summary"] = True

                updated = fallback_daily_update_if_needed(raw_data)
                if updated:
                    msg = fallback_daily_report_message()
                    if msg:
                        telegram_send(msg)

        except Exception as e:
            print("SCAN ERROR:", e)
            import traceback
            traceback.print_exc()

        time.sleep(60)

# ----------------- Thread Başlat -----------------

threading.Thread(target=background_loop, daemon=True).start()

# ----------------- Flask Routes -----------------

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

# ----------------- Flask Run -----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
