import os
import time
import threading
import requests
from datetime import datetime, timezone, time as dtime
from copy import deepcopy

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
        except Exception as e:
            log(f"TELEGRAM ERROR: {e}")

# =========================
# SAFE API SERIALIZER
# =========================
def clean_signal_for_api(s):
    if not isinstance(s, dict):
        return None
    try:
        return {
            "symbol": str(s.get("symbol")) if s.get("symbol") is not None else None,
            "type": str(s.get("type")) if s.get("type") is not None else None,
            "current_price": float(s.get("current_price")) if s.get("current_price") is not None else None,
            "strength": float(s.get("strength")) if s.get("strength") is not None else None,
            "ema_trend": str(s.get("trend_direction")) if s.get("trend_direction") else None,
            "volume_tag": str(s.get("volume_tag")) if s.get("volume_tag") else None,
            "algorithms": list(s.get("algorithms") or []),
            "combined_algorithms": list(s.get("combined_algorithms") or []),
            "rsi_1h": float(s.get("rsi_1h")) if s.get("rsi_1h") is not None else None,
            "rsi_4h": float(s.get("rsi_4h")) if s.get("rsi_4h") is not None else None,
            "resistance_1h": float(s.get("resistance_1h")) if s.get("resistance_1h") is not None else None,
            "resistance_4h": float(s.get("resistance_4h")) if s.get("resistance_4h") is not None else None,
            "first_signal_time": str(s.get("first_signal_time")) if s.get("first_signal_time") else None,
            "added_algorithms": list(s.get("added_algorithms") or []),
            "level_change": str(s.get("level_change")) if s.get("level_change") else None,
            "success": bool(s.get("success", False)),
            "current_time": str(s.get("time")) if s.get("time") else None
        }
    except Exception as e:
        log(f"[WARN] clean_signal_for_api hata: {e} | sinyal: {s}")
        return None

# =========================
# TELEGRAM FORMATS
# =========================
def format_signal_message(s, title="📈 SİNYAL"):
    if not s or not isinstance(s, dict):
        return None

    symbol = s.get("symbol")
    if not symbol:
        return None

    lines = [f"{title} | {symbol}", ""]

    price = s.get("current_price")
    strength = s.get("strength")
    trend = s.get("ema_trend")
    volume = s.get("volume_tag")
    if price is not None:
        lines.append(f"💰 Fiyat: {price:.2f} ₺")
    if strength is not None:
        lines.append(f"🔥 Güç: {strength:.1f} / 10")
    if trend:
        lines.append(f"📊 Trend: {trend}")
    if volume:
        lines.append(f"📉 Hacim: {volume}")

    algos = s.get("algorithms", [])
    added_algos = s.get("added_algorithms", [])
    if algos:
        pretty = {
            "l2": "EMA Trend",
            "l3": "Destek / Direnç",
            "l4": "Breakout",
            "three_peak": "Üç Zirve",
            "order_block": "Order Block",
            "squeeze": "Üçgen Sıkışma",
            "squeeze_break": "Üçgen Kırılım",
            "kombine": "Kombine",
            "super_kombine": "Süper Kombine"
        }
        lines.append("\n🧠 Tetiklenen Algoritmalar:")
        for a in algos:
            prefix = "+" if a in added_algos else "•"
            lines.append(f"{prefix} {pretty.get(a, a.upper())}")

    rsi_1h = s.get("rsi_1h")
    rsi_4h = s.get("rsi_4h")
    if rsi_1h or rsi_4h:
        lines.append(f"\n📊 RSI: 1h {rsi_1h:.2f} / 4h {rsi_4h:.2f}")

    res_1h = s.get("resistance_1h")
    res_4h = s.get("resistance_4h")
    if res_1h or res_4h:
        lines.append(f"📌 Direnç: 1h {res_1h} / 4h {res_4h}")

    first_time = s.get("first_signal_time")
    if first_time:
        lines.append(f"🕒 İlk Sinyal: {first_time}")

    return "\n".join(lines)

def format_success_message(s):
    if not s or not isinstance(s, dict):
        return ""
    symbol = s.get("symbol")
    entry = s.get("entry")
    target = s.get("target")
    algorithm = ", ".join(s.get("algorithms", []))
    return (
        f"🏆 BAŞARILI SİNYAL\n\n"
        f"📊 {symbol}\n"
        f"🎯 Giriş: {entry}\n"
        f"✅ Hedef: {target}\n"
        f"🧠 Algoritma: {algorithm}"
    )

# =========================
# MARKET CHECK
# =========================
def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return (
        now.weekday() < 5 and
        ((now.hour > 9) or (now.hour == 9 and now.minute >= 55)) and
        now.hour < 18
    )

# =========================
# STRONG SIGNAL LOGIC
# =========================
def is_strong_signal(s):
    if not isinstance(s, dict):
        return False
    if s.get("strength", 0) < 5:
        return False
    algos = s.get("algorithms", [])
    combined = s.get("combined_algorithms", [])
    # Güçlü al / kombine / süper kombine ve kurumsal AL mantığı
    if "super_kombine" in algos or "kombine" in algos or "order_block" in algos or combined:
        return True
    return False

def is_helper_only(s):
    """Yalnızca yardımcı algoritmalar tetiklenmiş sinyal"""
    if not isinstance(s, dict):
        return False
    algos = s.get("algorithms", [])
    strong_keys = ["super_kombine", "kombine", "order_block"]
    if any(a in strong_keys for a in algos):
        return False
    helper_keys = ["l2", "l3", "l4", "three_peak", "squeeze", "squeeze_break"]
    return any(a in helper_keys for a in algos)

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

            raw = fetch_bist_data()
            if not isinstance(raw, list):
                log(f"[WARN] fetch_bist_data geçersiz veri: {raw}")
                raw = []

            all_signals = []

            for item in raw:
                if not isinstance(item, dict):
                    log(f"[WARN] Geçersiz item: {item}")
                    continue
                try:
                    signals = process_signals(item)
                    if not isinstance(signals, list):
                        log(f"[WARN] process_signals geçersiz dönüş: {signals}")
                        continue
                except Exception as e:
                    log(f"[WARN] process_signals hata: {e} | item: {item}")
                    continue

                for s in signals:
                    if not isinstance(s, dict):
                        log(f"[WARN] Geçersiz sinyal: {s}")
                        continue
                    all_signals.append(deepcopy(s))
                    try:
                        update_success(s.get("symbol"), s.get("current_price"))
                    except Exception as e:
                        log(f"[WARN] update_success hata: {e} | sinyal: {s}")

            log(f"[SCAN] {len(all_signals)} sinyal işlendi")

            # Persistent ve filtreli sinyaller
            for s in all_signals:
                sym = s.get("symbol")
                if not sym:
                    continue

                # Persistent'te var mı kontrol
                existing = next((p for p in persistent_signals if p.get("symbol") == sym), None)

                # Eğer persistent yoksa ve güçlü al varsa normal mesaj
                if not existing and is_strong_signal(s):
                    msg = format_signal_message(s)
                    if msg:
                        telegram_send(msg)

                # Persistent var ve sadece helper iken güçlü al eklenirse
                elif existing and is_helper_only(existing) and is_strong_signal(s):
                    # Algoritmaları birleştir
                    combined_algos = list(set(existing.get("algorithms", []) + s.get("algorithms", [])))
                    s["algorithms"] = combined_algos
                    s["added_algorithms"] = s.get("algorithms", [])
                    msg = format_signal_message(s, title="📈 GÜÇLENEN SİNYAL")
                    if msg:
                        telegram_send(msg)

            # Persistent ve API için güncelle
            with data_lock:
                for s in all_signals:
                    if s not in persistent_signals:
                        persistent_signals.append(deepcopy(s))
                LATEST_SIGNALS = [clean_signal_for_api(deepcopy(s)) for s in persistent_signals]

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

    safe_signals = []
    with data_lock:
        for s in LATEST_SIGNALS:
            try:
                clean_s = deepcopy(s)
                safe_signals.append(clean_s)
            except Exception as e:
                log(f"[WARN] deepcopy sinyal hata: {e} | sinyal: {s}")

    return jsonify({
        "system_active": SYSTEM_STARTED,
        "market_open": market_open(),
        "last_scan": last_scan_str,
        "signals": safe_signals
    })

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
