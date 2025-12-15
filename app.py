import os
import threading
import time
import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone
from self_ping import start_self_ping

app = Flask(__name__)

# ================== GLOBALS ==================
LATEST_DATA = {"status": "init", "data": None, "timestamp": None}
data_lock = threading.Lock()

# ================== ENV SECURE ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = os.getenv("CHAT_IDS", "")
CHAT_IDS = [int(x.strip()) for x in CHAT_IDS.split(",") if x.strip()]

# ================== SIGNAL STATE ==================
sent_signals = {}
last_reset_date = None

# ================== JSON SAFE ==================
def json_safe(obj):
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj

# ================== TELEGRAM ==================
def telegram_send(text):
    if not TELEGRAM_TOKEN or not CHAT_IDS:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in CHAT_IDS:
        try:
            requests.post(url, json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=8)
        except:
            pass

# ================== 09:50 RESET ==================
def check_daily_reset():
    global sent_signals, last_reset_date
    now_tr = to_tr_timezone(datetime.now(timezone.utc))
    today = now_tr.date()

    if now_tr.hour == 9 and now_tr.minute >= 50:
        if last_reset_date != today:
            sent_signals = {}
            last_reset_date = today
            telegram_send("🔄 09:50 reset yapıldı – yeni gün taraması başladı")

# ================== SIGNAL PROCESS ==================
def process_and_notify(data):
    check_daily_reset()

    for item in data:
        symbol = item.get("symbol")
        if not symbol:
            continue

        sent_signals.setdefault(symbol, set())

        messages = []

        if item.get("last_signal") == "AL" and "AL" not in sent_signals[symbol]:
            messages.append("🟢 AL Sinyali")
            sent_signals[symbol].add("AL")

        if item.get("last_signal") == "SAT" and "SAT" not in sent_signals[symbol]:
            messages.append("🔴 SAT Sinyali")
            sent_signals[symbol].add("SAT")

        if item.get("composite_signal") and "COMBO" not in sent_signals[symbol]:
            messages.append("🚀 Kombine Sinyal")
            sent_signals[symbol].add("COMBO")

        if item.get("three_peak_break") and "TT" not in sent_signals[symbol]:
            messages.append("🔥 3’lü Tepe Kırılımı")
            sent_signals[symbol].add("TT")

        if not messages:
            continue

        dt_tr = to_tr_timezone(datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S (TR)")

        text = (
            f"<b>{symbol}</b>\n"
            f"{' | '.join(messages)}\n\n"
            f"Fiyat: {item.get('current_price')} TL\n"
            f"RSI: {item.get('RSI')}\n"
            f"Günlük Değişim: {item.get('daily_change')}\n"
            f"Hacim: {item.get('volume')}\n\n"
            f"Sinyal zamanı: {dt_tr}"
        )

        telegram_send(text)

# ================== LOOP ==================
def update_loop():
    telegram_send("🤖 Sistem başlatıldı – otomatik tarama aktif")

    while True:
        try:
            now_tr = to_tr_timezone(datetime.now(timezone.utc))

            # Borsa kapalıysa tarama yapma
            if now_tr.weekday() >= 5:
                time.sleep(300)
                continue

            data = fetch_bist_data()
            with data_lock:
                LATEST_DATA.update({
                    "status": "ok",
                    "timestamp": int(time.time()),
                    "data": json_safe(data)
                })
            process_and_notify(data)

        except Exception as e:
            app.logger.error(f"[LOOP ERROR] {e}")

        time.sleep(60)

# ================== START (ONCE) ==================
threading.Thread(target=update_loop, daemon=True).start()
start_self_ping()

# ================== ROUTES ==================
@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

@app.route("/api")
def api():
    with data_lock:
        return jsonify(LATEST_DATA)
