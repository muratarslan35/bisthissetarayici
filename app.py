import os
import time
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

print("TELEGRAM INIT:", bool(TELEGRAM_TOKEN), CHAT_IDS)

# ==================================================
# FLASK
# ==================================================
app = Flask(__name__)

LATEST_DATA = []
LATEST_SIGNALS = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False

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
        except Exception as e:
            print("TELEGRAM ERROR:", e)

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
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED, LATEST_SIGNALS, DAILY_SENT, LAST_DAY

    SYSTEM_STARTED = True
    print("BACKGROUND LOOP STARTED")

    while True:
        try:
            raw_data = fetch_bist_data()

            now = to_tr_timezone(datetime.now(timezone.utc))
            today = now.date()

            if LAST_DAY != today:
                DAILY_SENT = {"strong_stocks": False, "summary": False}
                LAST_DAY = today

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
                    if not sym or sym in seen_symbols:
                        continue
                    seen_symbols.add(sym)

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
                        "combined_algorithms": meta.get("combined_algorithms", [meta])
                    })

                with data_lock:
                    LATEST_SIGNALS = dashboard_signals

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
                            "📊 GÜN SONU BAŞARI ÖZETİ",
                            f"Tarih: {summary['date']}",
                            f"Toplam Başarılı: {summary['hit']} / {summary['total']}",
                            f"Başarı Oranı: %{summary['success_rate']:.2f}",
                            "",
                            "Başarılı Sinyaller:"
                        ]
                        for s in summary.get("success_signals", []):
                            lines.append(
                                f"• {s['symbol']} | {s['algorithm']} | {s['time']} | {s['price']}"
                            )
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
# API
# ==================================================
@app.route("/api")
def api():
    with data_lock:
        return jsonify(make_json_safe({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "signals": LATEST_SIGNALS
        }))

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    print("APP MAIN STARTED")

    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")

    threading.Thread(
        target=background_loop,
        daemon=True
    ).start()

    app.run(host="0.0.0.0", port=5000)
