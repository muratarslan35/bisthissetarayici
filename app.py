import os
import time
import threading
import requests
from datetime import datetime, timezone, time as dtime

from flask import Flask, jsonify, send_from_directory
from dotenv import load_dotenv

from fetch_bist import fetch_bist_data
from signal_engine import process_signals, update_success
from utils import to_tr_timezone

# =========================
# ENV
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS", "").split(",") if x]

# =========================
# FLASK
# =========================
app = Flask(__name__)

LATEST_SIGNALS = []
persistent_signals = []
SUCCESS_SENT = set()

SYSTEM_STARTED = False
LAST_SCAN_TS = None
sent_signal_cache = {}

data_lock = threading.Lock()
REPEAT_DELAY = 15 * 60

DAILY_SENT = {
    "summary": False
}

# =========================
# UTILS
# =========================
def log(msg):
    print(f"[APP] {msg}", flush=True)

def telegram_send(msg):
    if not TELEGRAM_TOKEN or not CHAT_IDS:
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

def format_signal_message(s):
    return (
        f"📊 {s.get('symbol')}\n"
        f"Fiyat: {s.get('current_price')}\n"
        f"Güç: {s.get('strength')}\n"
        f"Trend: {s.get('ema_trend')}\n"
        f"Algoritmalar: {', '.join(s.get('algorithms', []))}"
    )

def format_success_message(s):
    return (
        f"🏆 BAŞARILI SİNYAL\n\n"
        f"{s.get('symbol')}\n"
        f"Giriş: {s.get('entry')}\n"
        f"Hedef: {s.get('target')}\n"
        f"Algoritma: {s.get('algorithm')}"
    )

# =========================
# MARKET
# =========================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# =========================
# BACKGROUND LOOP
# =========================
def background_loop():
    global SYSTEM_STARTED, LAST_SCAN_TS, LATEST_SIGNALS

    SYSTEM_STARTED = True
    telegram_send("🤖 BIST SİNYAL BOTU BAŞLATILDI")
    log("Bot başlatıldı")

    last_day = None

    while True:
        try:
            now = to_tr_timezone(datetime.now(timezone.utc))
            LAST_SCAN_TS = int(now.timestamp())

            if not market_open():
                time.sleep(60)
                continue

            raw = fetch_bist_data() or []
            all_signals = []

            for item in raw:
                if not item or not isinstance(item, dict):
                    continue

                signals = process_signals(item) or []
                for s in signals:
                    if not s or not isinstance(s, dict):
                        continue

                    all_signals.append(s)

                    try:
                        update_success(
                            s.get("symbol"),
                            s.get("current_price")
                        )
                    except Exception:
                        pass

            # -------------------------
            # TELEGRAM SİNYALLER
            # -------------------------
            for s in all_signals:
                sym = s.get("symbol")
                typ = s.get("type")
                strength = s.get("strength", 0)

                if not sym or not typ:
                    continue

                key = (sym, typ)
                prev = sent_signal_cache.get(key, {"time": 0, "strength": 0})

                if (
                    strength > prev["strength"] or
                    time.time() - prev["time"] > REPEAT_DELAY
                ):
                    telegram_send(format_signal_message(s))
                    sent_signal_cache[key] = {
                        "time": time.time(),
                        "strength": strength
                    }

            # -------------------------
            # BAŞARILI SİNYAL
            # -------------------------
            for s in all_signals:
                sym = s.get("symbol")
                if s.get("success") and sym and sym not in SUCCESS_SENT:
                    telegram_send(format_success_message(s))
                    SUCCESS_SENT.add(sym)

            # -------------------------
            # GÜNLÜK ÖZET
            # -------------------------
            if now.time() >= dtime(17, 45) and not DAILY_SENT["summary"]:
                telegram_send(
                    f"📊 GÜNLÜK ÖZET\n\n"
                    f"Toplam sinyal: {len(persistent_signals)}\n"
                    f"Başarılı: {len(SUCCESS_SENT)}"
                )
                DAILY_SENT["summary"] = True

            # Yeni gün reset
            if last_day != now.date():
                last_day = now.date()
                DAILY_SENT["summary"] = False
                SUCCESS_SENT.clear()
                sent_signal_cache.clear()

            with data_lock:
                for s in all_signals:
                    if s not in persistent_signals:
                        persistent_signals.append(s)
                LATEST_SIGNALS = persistent_signals.copy()

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
    return jsonify({
        "system_active": SYSTEM_STARTED,
        "last_scan": LAST_SCAN_TS,
        "signals": LATEST_SIGNALS
    })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
