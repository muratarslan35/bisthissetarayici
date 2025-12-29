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
DAILY_SENT = {"summary": False}

# =========================
# UTILS
# =========================
def log(msg):
    print(f"[APP] {msg}", flush=True)

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

# =========================
# SAFE API SERIALIZER
# =========================
def clean_signal_for_api(s):
    """JSON-safe, circular refsiz sinyal"""
    if not isinstance(s, dict):
        return None

    return {
        "symbol": s.get("symbol"),
        "type": s.get("type"),
        "current_price": s.get("current_price"),
        "strength": s.get("strength"),
        "ema_trend": s.get("ema_trend"),
        "timeframe": s.get("timeframe"),
        "entry": s.get("entry"),
        "target": s.get("target"),
        "stop": s.get("stop"),
        "algorithms": list(s.get("algorithms", [])),
        "success": bool(s.get("success", False))
    }

# =========================
# TELEGRAM FORMAT
# =========================
def format_signal_message(s):
    symbol = s.get("symbol")
    if not symbol:
        return None

    lines = [f"📊 {symbol} | {s.get('type', 'SİNYAL')}"]

    if s.get("current_price") is not None:
        lines.append(f"💰 Fiyat: {round(s['current_price'], 2)}")

    if s.get("strength") is not None:
        lines.append(f"🔥 Güç: {s['strength']}")

    if s.get("ema_trend"):
        lines.append(f"📈 Trend: {s['ema_trend']}")

    if s.get("timeframe"):
        lines.append(f"⏱ Zaman: {s['timeframe']}")

    if s.get("entry"):
        lines.append(f"🎯 Giriş: {round(s['entry'], 2)}")
    if s.get("target"):
        lines.append(f"✅ Hedef: {round(s['target'], 2)}")
    if s.get("stop"):
        lines.append(f"🛑 Stop: {round(s['stop'], 2)}")

    algos = s.get("algorithms", [])
    if algos:
        pretty = {
            "l1": "RSI",
            "l2": "EMA",
            "l3": "DESTEK/DİRENÇ",
            "l4": "BREAKOUT",
            "l5": "HACİM",
            "squeeze": "SQUEEZE"
        }
        lines.append(
            "🧠 Algoritmalar: " +
            ", ".join(pretty.get(a, a.upper()) for a in algos)
        )

    return "\n".join(lines)

def format_success_message(s):
    return (
        f"🏆 BAŞARILI SİNYAL\n\n"
        f"{s.get('symbol')}\n"
        f"Giriş: {s.get('entry')}\n"
        f"Hedef: {s.get('target')}"
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
                signals = process_signals(item) or []
                for s in signals:
                    all_signals.append(s)
                    update_success(s.get("symbol"), s.get("current_price"))

            # Telegram sinyaller
            for s in all_signals:
                sym = s.get("symbol")
                typ = s.get("type")
                strength = s.get("strength", 0)

                if not sym or not typ:
                    continue

                key = (sym, typ)
                prev = sent_signal_cache.get(key, {"time": 0, "strength": 0})

                if strength > prev["strength"] or time.time() - prev["time"] > REPEAT_DELAY:
                    msg = format_signal_message(s)
                    if msg:
                        telegram_send(msg)
                        sent_signal_cache[key] = {
                            "time": time.time(),
                            "strength": strength
                        }

            # Başarılı sinyal
            for s in all_signals:
                sym = s.get("symbol")
                if s.get("success") and sym and sym not in SUCCESS_SENT:
                    telegram_send(format_success_message(s))
                    SUCCESS_SENT.add(sym)

            # Günlük özet
            if now.time() >= dtime(17, 45) and not DAILY_SENT["summary"]:
                telegram_send(
                    f"📊 GÜNLÜK ÖZET\n\n"
                    f"Toplam sinyal: {len(persistent_signals)}\n"
                    f"Başarılı: {len(SUCCESS_SENT)}"
                )
                DAILY_SENT["summary"] = True

            if last_day != now.date():
                last_day = now.date()
                DAILY_SENT["summary"] = False
                SUCCESS_SENT.clear()
                sent_signal_cache.clear()

            with data_lock:
                for s in all_signals:
                    if s not in persistent_signals:
                        persistent_signals.append(s)

                # 🔒 API için TEMİZ KOPYA
                LATEST_SIGNALS = [
                    clean_signal_for_api(s)
                    for s in persistent_signals
                    if clean_signal_for_api(s)
                ]

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
    last_scan_str = None
    if LAST_SCAN_TS:
        dt = to_tr_timezone(datetime.fromtimestamp(LAST_SCAN_TS, tz=timezone.utc))
        last_scan_str = dt.strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({
        "system_active": SYSTEM_STARTED,
        "market_open": market_open(),
        "last_scan": last_scan_str,
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
