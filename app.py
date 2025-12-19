import os
import time
import threading
import requests
from datetime import datetime, timezone, date
from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

from fetch_bist import fetch_bist_data
from signal_engine import safe_process_bist_data, success_tracker
from utils import to_tr_timezone

# ==================================================
# ENV
# ==================================================
load_dotenv("/home/ubuntu/bistbot/.env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# ==================================================
# APP
# ==================================================
app = Flask(__name__)

LATEST_DATA = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
FIRST_SCAN_DONE = False
TODAY = None

data_lock = threading.Lock()

# ==================================================
# TELEGRAM
# ==================================================
def telegram_send(msg):
    if not TELEGRAM_TOKEN:
        return
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=5
            )
        except:
            pass

# ==================================================
# MARKET TIME
# ==================================================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        (
            now.hour > 9 or
            (now.hour == 9 and now.minute >= 55)
        ) and
        now.hour < 18
    )

# ==================================================
# DAY END SUMMARY
# ==================================================
def send_day_summary():
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    rows = []

    for symbol, days in success_tracker.items():
        d = days.get(today)
        if d and d.get("hit"):
            rows.append(f"• {symbol} 🎯")

    if rows:
        telegram_send(
            "📊 GÜN SONU BAŞARILI SİNYALLER\n\n" +
            "\n".join(rows)
        )
    else:
        telegram_send("📊 Bugün başarılı sinyal olmadı.")

# ==================================================
# BACKGROUND LOOP
# ==================================================
def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED
    global FIRST_SCAN_DONE, TODAY

    SYSTEM_STARTED = True
    telegram_send("🤖 Sistem başlatıldı – Oracle VM aktif")

    while True:
        try:
            now_tr = to_tr_timezone(datetime.now(timezone.utc))
            today = now_tr.date()

            # Yeni gün resetleri
            if TODAY != today:
                TODAY = today
                FIRST_SCAN_DONE = False
                telegram_send("🌅 Yeni işlem günü başladı")

            data = fetch_bist_data()
            signals = safe_process_bist_data(data)

            with data_lock:
                LATEST_DATA = data
                LAST_SCAN_TS = int(time.time())

            # ==========================
            # SABAH İLK TARAMA
            # ==========================
            if market_open() and not FIRST_SCAN_DONE:
                FIRST_SCAN_DONE = True
                telegram_send(
                    f"⏰ 09:55 İlk tarama tamamlandı\n"
                    f"📌 Taranan hisse: {len(data)}"
                )

            # ==========================
            # GÜN İÇİ YENİ SİNYALLER
            # ==========================
            for key, msg, meta in signals:
                # Sabah açılışta super kombine engeli (15m datasız)
                if not market_open() and meta.get("type") == "super":
                    continue
                telegram_send(msg)

            # ==========================
            # GÜN SONU (18:10)
            # ==========================
            if now_tr.hour == 18 and now_tr.minute == 10:
                send_day_summary()

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

# ==================================================
# THREAD
# ==================================================
threading.Thread(target=background_loop, daemon=True).start()

# ==================================================
# API (DASHBOARD)
# ==================================================
@app.route("/api")
def api():
    with data_lock:
        today = to_tr_timezone(datetime.now(timezone.utc)).date()

        success_today = []
        for symbol, days in success_tracker.items():
            d = days.get(today)
            if d:
                success_today.append({
                    "symbol": symbol,
                    "entry": d["entry"],
                    "target": d["target"],
                    "hit": d["hit"]
                })

        return jsonify({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "data": LATEST_DATA,
            "success_table": success_today
        })

@app.route("/wake")
def wake():
    return jsonify({"ok": 1})

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# ==================================================
# MAIN
# ==================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
