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
# TREND & GOLDEN CROSS
# ======================================================

def ema_trend(e20, e50, e200):
    if e20 > e50 > e200:
        return "📈 YUKARI"
    if e20 < e50 < e200:
        return "📉 AŞAĞI"
    return "➖ YATAY"

def golden_cross(tf1d):
    return bool(tf1d and tf1d.get("ema50") > tf1d.get("ema200"))

# ======================================================
# ORDER BLOCK
# ======================================================

def detect_order_block(df):
    if df is None or len(df) < 25:
        return False

    last = df.iloc[-1]
    red = df.iloc[-8:-1]
    red = red[red["Close"] < red["Open"]]

    if red.empty:
        return False

    ob = red.iloc[-1]
    return last["Close"] > ob["High"]

# ======================================================
# L2 L3 L4
# ======================================================

def detect_l2_l3_l4(df, price):
    helpers = []
    levels = nearest_support_resistance_from_history(df)

    for lvl in levels:
        if price <= lvl["level"]:
            continue

        s = lvl.get("strength", 0)
        if s >= 4:
            helpers.append(("L4 MAJÖR KIRILIM", 20))
        elif s == 3:
            helpers.append(("L3 GÜÇLÜ KIRILIM", 12))
        elif s == 2:
            helpers.append(("L2 KIRILIM", 6))

    return helpers

# ======================================================
# HELPERS
# ======================================================

def helper_indicators(item):
    helpers = []

    tf15 = item["tf"]["15m"]
    tf1h = item["tf"]["1h"]
    tf4h = item["tf"]["4h"]
    tf1d = item["tf"].get("1d")

    rsi = tf15.get("rsi")
    if rsi is not None:
        if rsi < 30:
            helpers.append(("RSI AŞIRI SATIM", 10))
        elif rsi < 35:
            helpers.append(("RSI DÜŞÜK", 5))

    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 10))

    df = tf15.get("df")
    if df is not None:
        if detect_three_peaks(df["Close"]):
            helpers.append(("3LÜ TEPE", 10))

        if detect_order_block(df):
            helpers.append(("ORDER BLOCK", 20))

        br = detect_support_resistance_break(df)
        if br and br["type"] == "RESISTANCE_BREAK":
            helpers.append(("DİRENÇ KIRILIMI", 15))

        helpers.extend(detect_l2_l3_l4(df, item["current_price"]))

    if (
        tf15["ema20"] > tf15["ema50"] and
        tf1h["ema20"] > tf1h["ema50"] and
        tf4h["ema20"] > tf4h["ema50"]
    ):
        helpers.append(("EMA UYUMU", 15))

    if golden_cross(tf1d):
        helpers.append(("GOLDEN CROSS", 15))

    return helpers

# ======================================================
# ANA ALGO
# ======================================================

def kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1h = item["tf"]["1h"]
    tf4h = item["tf"]["4h"]

    if not (tf15["ema20"] > tf15["ema50"] > tf15["ema200"]):
        return None
    if not (tf1h["ema20"] > tf1h["ema50"]):
        return None
    if not (tf4h["ema20"] > tf4h["ema50"]):
        return None

    return {"main_type": "KOMBİNE", "base_strength": 70}

def super_kombine_signal(item):
    base = kombine_signal(item)
    if not base:
        return None

    if item["tf"]["15m"]["rsi"] < 28:
        base["main_type"] = "SÜPER KOMBİNE"
        base["base_strength"] = 90
        return base

    return None

# ======================================================
# PROCESS
# ======================================================

def process_symbol_signals(item):
    symbol = item["symbol"]
    price = item["current_price"]

    main = super_kombine_signal(item) or kombine_signal(item)
    if not main:
        return []

    algo = main["main_type"]

    helpers = helper_indicators(item)
    helper_names = set(h[0] for h in helpers)
    helper_strength = sum(h[1] for h in helpers)

    total = main["base_strength"] + helper_strength
    now_h = tr_now().strftime("%H:%M")

    prev = LAST_SIGNAL_STATE.get(symbol)
    strengthened = False
    added = []

    if prev:
        added = list(helper_names - prev["helpers"])
        if total >= prev["strength"] + 20:
            strengthened = True
        elif in_repeat_block(symbol, algo):
            return []

    if in_repeat_block(symbol, algo) and not strengthened:
        return []

    mark_sent(symbol, algo)

    history = prev["history"][:] if prev else [(now_h, f"{algo} sinyal")]
    helpers_set = prev["helpers"].copy() if prev else set()

    if strengthened and added:
        history.append((now_h, f"{' + '.join(added)} eklendi"))

    helpers_set |= helper_names

    LAST_SIGNAL_STATE[symbol] = {
        "strength": total,
        "helpers": helpers_set,
        "history": history
    }

    signal = {
        "symbol": symbol,
        "price": fmt(price),
        "action": "GÜÇLENEN SİNYAL" if strengthened else "GÜÇLÜ AL",
        "main_algorithm": algo,
        "strength": total,
        "ema_trend": ema_trend(
            item["tf"]["15m"]["ema20"],
            item["tf"]["15m"]["ema50"],
            item["tf"]["15m"]["ema200"]
        ),
        "helpers": list(helpers_set),
        "golden_cross": golden_cross(item["tf"].get("1d")),
        "history": history,
        "time": tr_now().strftime("%H:%M:%S"),
        "tf": item["tf"]
    }

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
# SIGNAL FORMAT
# ======================================================

def format_signal_message(signal):
    lines = []

    lines.append(f"📊 {signal['symbol']}")
    lines.append(f"💰 Fiyat: {signal['price']}")
    lines.append(f"⚡ Sinyal: {signal['action']}")
    lines.append(f"🧠 Algo: {signal['main_algorithm']}")
    lines.append(f"🔥 Güç: {signal['strength']}")
    lines.append(f"📈 Trend: {signal['ema_trend']}")

    if signal.get("golden_cross"):
        lines.append("✨ Golden Cross (1D)")

    if signal.get("helpers"):
        lines.append("\n🧩 Destekleyiciler:")
        for h in signal["helpers"]:
            lines.append(f"• {h}")

    if signal.get("history"):
        lines.append("\n🕒 Gelişim:")
        for t, msg in signal["history"][-4:]:
            lines.append(f"{t} → {msg}")

    lines.append(f"\n⏰ {signal['time']}")
    return "\n".join(lines)

# ======================================================
# BULK PROCESS
# ======================================================

def process_signals(data):
    all_signals = []

    for item in data:
        try:
            sigs = process_symbol_signals(item)
            if sigs:
                all_signals.extend(sigs)
        except Exception:
            continue

    return all_signals

# ======================================================
# SUCCESS UPDATE
# ======================================================

def update_success(symbol, price):
    hits = update_success_targets(symbol, price)

    messages = []
    for h in hits:
        messages.append(
            f"🎯 HEDEF GELDİ\n"
            f"{h['symbol']} – {h['algorithm']}"
        )

    return messages
