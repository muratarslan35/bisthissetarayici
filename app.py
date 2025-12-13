# app.py
import os
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone
from self_ping import start_self_ping

app = Flask(__name__)

# ================== GLOBALS ==================
LATEST_DATA = {"status": "init", "data": None, "timestamp": None}
data_lock = threading.Lock()

TELEGRAM_TOKEN = "8588829956:AAEK2-wa75CoHQPjPFEAUU_LElRBduC-_TU"
CHAT_IDS = [661794787]

# Aynı gün içinde tekrar gitmemesi için
sent_signals = {}   # { symbol: set(signal_keys) }
last_reset_date = None

# ================== TELEGRAM ==================
def telegram_send(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for cid in CHAT_IDS:
        try:
            payload = {
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            app.logger.error(f"[TELEGRAM ERROR] {e}")

# ================== 09:00 RESET ==================
def check_daily_reset():
    """
    Her gün SAAT 09:00 (TR) olduğunda
    gönderilmiş sinyalleri sıfırlar
    """
    global sent_signals, last_reset_date

    now_tr = to_tr_timezone(datetime.now(timezone.utc))
    today = now_tr.date()

    if now_tr.hour >= 9:
        if last_reset_date != today:
            sent_signals = {}
            last_reset_date = today
            app.logger.info("🔄 09:00 reset yapıldı – sinyaller sıfırlandı")

# ================== MA FORMAT ==================
def fmt_ma(ma):
    out = []
    for k, v in ma.items():
        if v == "above":
            out.append(f"{k}: ÜSTTE")
        elif v == "below":
            out.append(f"{k}: ALTI")
        elif v == "golden_cross":
            out.append(f"{k}: GOLDEN CROSS")
        elif v == "death_cross":
            out.append(f"{k}: DEATH CROSS")
    return " | ".join(out)

# ================== SIGNAL PROCESS ==================
def process_and_notify(data):
    global sent_signals

    check_daily_reset()

    for item in data:
        symbol = item.get("symbol")
        if not symbol:
            continue

        sent_signals.setdefault(symbol, set())

        price = item.get("current_price")
        rsi = item.get("RSI")
        trend = item.get("trend")
        volume = item.get("volume")
        daily_change = item.get("daily_change")
        ma = item.get("ma_breaks", {})

        dt_tr = to_tr_timezone(datetime.now(timezone.utc))
        ts = dt_tr.strftime("%Y-%m-%d %H:%M:%S (TR)")

        messages = []

        # AL / SAT
        if item.get("last_signal") == "AL" and "AL" not in sent_signals[symbol]:
            messages.append("🟢 AL Sinyali")
            sent_signals[symbol].add("AL")

        if item.get("last_signal") == "SAT" and "SAT" not in sent_signals[symbol]:
            messages.append("🔴 SAT Sinyali")
            sent_signals[symbol].add("SAT")

        # Kombine
        if item.get("composite_signal") and "COMBO" not in sent_signals[symbol]:
            messages.append("🚀🚀🚀 Kombine Sinyal")
            sent_signals[symbol].add("COMBO")

        # 3’lü tepe
        if item.get("three_peak_break") and "TT" not in sent_signals[symbol]:
            messages.append("🔥🔥 3'lü tepe kırılımı")
            sent_signals[symbol].add("TT")

        # 11 / 15 mumlar (sadece kombineye etki ediyor, spam yok)
        if item.get("green_mum_11"):
            sent_signals[symbol].add("G11")
        if item.get("green_mum_15"):
            sent_signals[symbol].add("G15")

        if not messages:
            continue

        text = (
            f"<b>Hisse Takip: {symbol}</b>\n"
            f"{' | '.join(messages)}\n\n"
            f"Fiyat: {price} TL\n"
            f"Trend: {trend}\n"
            f"RSI: {rsi}\n"
            f"Günlük Değişim: {daily_change}\n"
            f"Hacim: {volume}\n\n"
            f"MA: {fmt_ma(ma)}\n"
            f"Sinyal zamanı: {ts}"
        )

        telegram_send(text)

# ================== LOOP ==================
def update_loop():
    telegram_send("🤖 Sistem aktif – tarama başladı")

    while True:
        try:
            data = fetch_bist_data()
            with data_lock:
                LATEST_DATA.update({
                    "status": "ok",
                    "timestamp": int(time.time()),
                    "data": data
                })
            process_and_notify(data)
        except Exception as e:
            app.logger.error(f"[LOOP ERROR] {e}")
        time.sleep(60)

# ================== START ==================
_started = False
@app.before_request
def start_bg():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=update_loop, daemon=True).start()
        start_self_ping()

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

@app.route("/api")
def api():
    with data_lock:
        return jsonify(LATEST_DATA)
