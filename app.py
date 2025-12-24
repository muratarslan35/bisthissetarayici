import os
import time
import json
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv
from collections import defaultdict

from fetch_bist import fetch_bist_data
from signal_engine import (
    safe_process_bist_data,
    scan_strong_stocks,
    daily_success_summary,
    format_signal_message
)
from utils import to_tr_timezone

from fallback_manager import (
    fallback_daily_update_if_needed,
    fallback_daily_report_message
)

# ==================================================
# ENV
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

SUCCESS_STORE_FILE = os.path.join(BASE_DIR, "successful_signals.json")

# ==================================================
# FLASK
# ==================================================
app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False

SUCCESS_SIGNALS = []

data_lock = threading.Lock()

# ==================================================
# GÜN SONU BAYRAKLARI
# ==================================================
DAILY_SENT = {"strong_stocks": False, "summary": False}
LAST_DAY = None

# ==================================================
# JSON SAFE
# ==================================================
def make_json_safe(obj):
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_safe(i) for i in obj]
    elif hasattr(obj, "item"):
        return obj.item()
    return obj

# ==================================================
# SUCCESS STORE
# ==================================================
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

# ==================================================
# TELEGRAM
# ==================================================
def telegram_send(msg):
    if not TELEGRAM_TOKEN or not CHAT_IDS or not msg:
        return
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=5
            )
        except Exception:
            pass

# ==================================================
# MARKET HOURS
# ==================================================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# ==================================================
# BACKGROUND LOOP
# ==================================================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED, LATEST_SIGNALS, DAILY_SENT, LAST_DAY, SUCCESS_SIGNALS

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU AKTİF")

    load_success_store()

    while True:
        try:
            raw_data = fetch_bist_data()

            now = to_tr_timezone(datetime.now(timezone.utc))
            today = now.date()

            if LAST_DAY != today:
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                LAST_DAY = today
                reset_success_store()

            with data_lock:
                LATEST_DATA = raw_data
                LAST_SCAN_TS = int(time.time())

            # ================= MARKET AÇIK =================
            if market_open():
                signals = safe_process_bist_data(raw_data, market_open=True)

                grouped = defaultdict(list)
                for meta in signals:
                    sym = meta.get("symbol")
                    if sym:
                        grouped[sym].append(meta)

                for symbol, alg_list in grouped.items():
                    msg = format_signal_message(symbol, alg_list)
                    telegram_send(msg)

                dashboard_signals = []
                seen_symbols = set()
                for meta in signals:
                    sym = meta.get("symbol")
                    if sym in seen_symbols:
                        continue
                    seen_symbols.add(sym)

                    combined_algorithms = meta.get("combined_algorithms", [meta])

                    success_hit = False
                    for s in SUCCESS_SIGNALS:
                        if s["symbol"] == sym:
                            success_hit = True
                            break

                    dashboard_signals.append({
                        "symbol": sym,
                        "price": meta.get("price") or meta.get("current_price"),
                        "type": meta.get("type"),
                        "title": meta.get("title", meta.get("type")),
                        "direction": meta.get("direction", "up"),
                        "trend_strength": meta.get("trend_strength", meta.get("strength", 50)),
                        "support": meta.get("support"),
                        "resistance": meta.get("resistance"),
                        "signal_type": meta.get("type"),
                        "current_price": meta.get("price") or meta.get("current_price"),
                        "rsi": meta.get("rsi"),
                        "time": to_tr_timezone(datetime.now(timezone.utc)).strftime("%H:%M:%S"),
                        "details": meta,
                        "combined_algorithms": combined_algorithms,
                        "success": success_hit
                    })

                with data_lock:
                    LATEST_SIGNALS = dashboard_signals

                summary = daily_success_summary(include_details=True, max_failures=0)
                if summary:
                    for s in summary.get("success_signals", []):
                        if not any(x["symbol"] == s["symbol"] for x in SUCCESS_SIGNALS):
                            SUCCESS_SIGNALS.append(s)
                            save_success_store()

            # ================= MARKET KAPALI =================
            else:
                if not DAILY_SENT["strong_stocks"]:
                    strong = scan_strong_stocks(raw_data)
                    if strong:
                        telegram_send(
                            "📌 PİYASA KAPALI – GÜÇLÜ HİSSELER\n\n" +
                            "\n".join(strong)
                        )
                    DAILY_SENT["strong_stocks"] = True

                if not DAILY_SENT["summary"]:
                    summary = daily_success_summary(include_details=True, max_failures=0)
                    if summary:
                        lines = [
                            f"📊 GÜN SONU BAŞARI ÖZETİ",
                            f"Tarih: {summary['date']}",
                            f"Toplam Başarılı: {summary['hit']} / Toplam Sinyal: {summary['total']}",
                            f"Başarı Oranı: %{summary['success_rate']:.2f}",
                            "",
                            "Başarılı Sinyaller:"
                        ]
                        for s in summary.get("success_signals", []):
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

        time.sleep(60)

# ==================================================
# THREAD
# ==================================================
threading.Thread(target=background_loop, daemon=True).start()

# ==================================================
# API
# ==================================================
@app.route("/api")
def api():
    with data_lock:
        return jsonify(make_json_safe({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS,
            "successful_signals": SUCCESS_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
