from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils import (
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history
)

# ======================================================
# GLOBAL STATE
# ======================================================

REPEAT_BLOCK_MINUTES = 45
TARGET_PCT = 0.015

LAST_SENT = {}
SUCCESS_TRACKER = {}
LAST_SIGNAL_STATE = {}

TR_TZ = ZoneInfo("Europe/Istanbul")

# ======================================================
# TIME
# ======================================================

def tr_now():
    return datetime.now(TR_TZ)

def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

# ======================================================
# REPEAT BLOCK
# ======================================================

def in_repeat_block(symbol, algo):
    t = LAST_SENT.get((symbol, algo))
    return t and tr_now() < t

def mark_sent(symbol, algo):
    LAST_SENT[(symbol, algo)] = tr_now() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

# ======================================================
# TREND
# ======================================================

def ema_trend(e20, e50, e200):
    if e20 > e50 > e200:
        return "📈 YUKARI"
    if e20 < e50 < e200:
        return "📉 AŞAĞI"
    return "➖ YATAY"

# ======================================================
# CORE ALGORITHMS
# ======================================================

def kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")

    if not tf1h or not tf4h:
        return None

    if not (tf15["ema20"] > tf15["ema50"] > tf15["ema200"]):
        return None
    if not (tf1h["ema20"] > tf1h["ema50"]):
        return None
    if not (tf4h["ema20"] > tf4h["ema50"]):
        return None

    return {"main_type": "KOMBİNE", "base_strength": 60}

def super_kombine_signal(item):
    base = kombine_signal(item)
    if not base:
        return None

    rsi = item["tf"]["15m"].get("rsi")
    if rsi is not None and rsi < 28:
        base["main_type"] = "SÜPER KOMBİNE"
        base["base_strength"] = 85
        return base

    return None

# ======================================================
# HELPERS (GERÇEKTEN YARDIMCI)
# ======================================================

def helper_indicators(item):
    helpers = []

    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")

    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 8))

    rsi = tf15.get("rsi")
    if rsi is not None and rsi < 35:
        helpers.append(("RSI DÜŞÜK", 6))

    df = tf15.get("df")
    if df is not None:
        if detect_three_peaks(df["Close"]):
            helpers.append(("3LÜ TEPE", -10))

        if detect_support_resistance_break(df):
            helpers.append(("DİRENÇ KIRILIMI", 10))

    if tf1h and tf4h:
        if tf1h["ema20"] > tf1h["ema50"] and tf4h["ema20"] > tf4h["ema50"]:
            helpers.append(("EMA UYUMU", 10))

    return helpers

# ======================================================
# MAIN PROCESS
# ======================================================

def process_symbol_signals(item):
    symbol = item["symbol"]
    price = item["current_price"]

    main = super_kombine_signal(item) or kombine_signal(item)
    if not main:
        return []

    algo = main["main_type"]

    if in_repeat_block(symbol, algo):
        return []

    helpers = helper_indicators(item)
    helper_strength = sum(h[1] for h in helpers)
    helper_names = [h[0] for h in helpers]

    total_strength = main["base_strength"] + helper_strength

    tf15 = item["tf"]["15m"]
    df = tf15.get("df")

    r1h = nearest_support_resistance_from_history(
        item["tf"]["1h"]["df"]
    ) if item["tf"].get("1h") else []

    r4h = nearest_support_resistance_from_history(
        item["tf"]["4h"]["df"]
    ) if item["tf"].get("4h") else []

    signal = {
        "symbol": symbol,
        "price": fmt(price),
        "action": "GÜÇLÜ AL" if algo == "KOMBİNE" else "SÜPER GÜÇLÜ AL",
        "main_algorithm": algo,
        "strength": total_strength,
        "ema_trend": ema_trend(
            tf15["ema20"], tf15["ema50"], tf15["ema200"]
        ),
        "helpers": helper_names,
        "resistance_1h": r1h[0]["level"] if r1h else None,
        "resistance_4h": r4h[0]["level"] if r4h else None,
        "time": tr_now().strftime("%H:%M:%S"),
        "tf": item["tf"]
    }

    mark_sent(symbol, algo)
    register_success_candidate(signal)

    return [signal]

# ======================================================
# SUCCESS
# ======================================================

def register_success_candidate(signal):
    today = tr_now().date()
    SUCCESS_TRACKER.setdefault(today, {})
    SUCCESS_TRACKER[today][(signal["symbol"], signal["main_algorithm"])] = {
        "entry": signal["price"],
        "target": signal["price"] * (1 + TARGET_PCT),
        "hit": False
    }

def update_success_targets(symbol, price):
    today = tr_now().date()
    hits = []

    for (sym, algo), d in SUCCESS_TRACKER.get(today, {}).items():
        if sym == symbol and not d["hit"] and price >= d["target"]:
            d["hit"] = True
            hits.append({"symbol": sym, "algorithm": algo})

    return hits

# ======================================================
# FORMAT MESSAGE
# ======================================================

def format_signal_message(signal):
    lines = [
        f"📊 {signal['symbol']}",
        f"💰 Fiyat: {signal['price']}",
        f"⚡ Sinyal: {signal['action']}",
        f"🧠 Algo: {signal['main_algorithm']}",
        f"🔥 Güç: {signal['strength']}",
        f"📈 Trend: {signal['ema_trend']}",
    ]

    if signal.get("resistance_1h"):
        lines.append(f"🧱 1H Direnç: {signal['resistance_1h']}")
    if signal.get("resistance_4h"):
        lines.append(f"🧱 4H Direnç: {signal['resistance_4h']}")

    if signal.get("helpers"):
        lines.append("\n🧩 Destekleyiciler:")
        for h in signal["helpers"]:
            lines.append(f"• {h}")

    lines.append(f"\n⏰ {signal['time']}")
    return "\n".join(lines)
