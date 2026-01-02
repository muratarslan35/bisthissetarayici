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
# GOLDEN CROSS
# ======================================================

def golden_cross(tf1d):
    return bool(tf1d and tf1d.get("ema50") > tf1d.get("ema200"))

# ======================================================
# ORDER BLOCK
# ======================================================

def detect_order_block(df):
    if df is None or len(df) < 20:
        return False

    last = df.iloc[-1]
    reds = df.iloc[-8:-1]
    reds = reds[reds["Close"] < reds["Open"]]

    if reds.empty:
        return False

    ob = reds.iloc[-1]
    return last["Close"] > ob["High"]

# ======================================================
# L2 / L3 / L4
# ======================================================

def detect_l2_l3_l4(df, price):
    helpers = []
    levels = nearest_support_resistance_from_history(df)

    for lvl in levels:
        if price <= lvl["level"]:
            continue

        s = lvl.get("strength", 0)
        if s == 4:
            helpers.append(("L4 MAJÖR KIRILIM", 20))
        elif s == 3:
            helpers.append(("L3 GÜÇLÜ KIRILIM", 12))
        elif s == 2:
            helpers.append(("L2 KIRILIM", 6))

    return helpers

# ======================================================
# HELPERS (SADECE GÜÇLENDİRİR)
# ======================================================

def helper_indicators(item):
    helpers = []

    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    tf1d = item["tf"].get("1d")

    # RSI
    rsi = tf15.get("rsi")
    if rsi is not None:
        if rsi < 28:
            helpers.append(("RSI AŞIRI SATIM", 12))
        elif rsi < 35:
            helpers.append(("RSI DÜŞÜK", 6))

    # Hacim
    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 10))

    df = tf15.get("df")
    if df is not None:
        if detect_three_peaks(df["Close"]):
            helpers.append(("3LÜ TEPE", 8))

        if detect_order_block(df):
            helpers.append(("ORDER BLOCK", 15))

        br = detect_support_resistance_break(df)
        if br and br["type"] == "RESISTANCE_BREAK":
            helpers.append(("DİRENÇ KIRILIMI", 12))

        helpers.extend(detect_l2_l3_l4(df, item["current_price"]))

    # EMA uyumu (çok kritik → tek başına yetmez)
    if tf1h and tf4h:
        if (
            tf15["ema20"] > tf15["ema50"] and
            tf1h["ema20"] > tf1h["ema50"] and
            tf4h["ema20"] > tf4h["ema50"]
        ):
            helpers.append(("EMA UYUMU", 10))

    if golden_cross(tf1d):
        helpers.append(("GOLDEN CROSS", 10))

    return helpers

# ======================================================
# ANA ALGORİTMALAR
# ======================================================

def kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")

    if not tf1h or not tf4h:
        return None

    # 🔒 SIKI ANA ŞARTLAR
    if not (tf15["ema20"] > tf15["ema50"] > tf15["ema200"]):
        return None
    if not (tf1h["ema20"] > tf1h["ema50"]):
        return None
    if not (tf4h["ema20"] > tf4h["ema50"]):
        return None

    return {
        "main_type": "KOMBİNE",
        "base_strength": 55
    }

def super_kombine_signal(item):
    base = kombine_signal(item)
    if not base:
        return None

    tf15 = item["tf"]["15m"]

    # ❗ SÜPER KOMBİNE ZOR
    if (
        tf15.get("rsi") is not None and
        tf15["rsi"] < 30 and
        tf15.get("volume_ok")
    ):
        return {
            "main_type": "SÜPER KOMBİNE",
            "base_strength": 80
        }

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

    total_strength = main["base_strength"] + helper_strength
    now_h = tr_now().strftime("%H:%M")

    prev = LAST_SIGNAL_STATE.get(symbol)
    strengthened = False
    added = []

    if prev:
        added = list(helper_names - prev["helpers"])
        if total_strength >= prev["strength"] + 15:
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
        "strength": total_strength,
        "helpers": helpers_set,
        "history": history
    }

    # Dirençler
    df15 = item["tf"]["15m"]["df"]
    sr = nearest_support_resistance_from_history(df15)

    r1h = next((x["level"] for x in sr if x["tf"] == "1h"), None)
    r4h = next((x["level"] for x in sr if x["tf"] == "4h"), None)

    signal = {
        "symbol": symbol,
        "price": fmt(price),
        "action": "GÜÇLENEN SİNYAL" if strengthened else "GÜÇLÜ AL",
        "main_algorithm": algo,
        "strength": total_strength,
        "ema_trend": ema_trend(
            item["tf"]["15m"]["ema20"],
            item["tf"]["15m"]["ema50"],
            item["tf"]["15m"]["ema200"]
        ),
        "helpers": list(helpers_set),
        "golden_cross": golden_cross(item["tf"].get("1d")),
        "history": history,
        "time": tr_now().strftime("%H:%M:%S"),
        "tf": item["tf"],
        "resistance_1h": fmt(r1h),
        "resistance_4h": fmt(r4h)
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
# FORMAT
# ======================================================

def format_signal_message(signal):
    lines = [
        f"📊 {signal['symbol']}",
        f"💰 Fiyat: {signal['price']}",
        f"⚡ Sinyal: {signal['action']}",
        f"🧠 Algo: {signal['main_algorithm']}",
        f"🔥 Güç: {signal['strength']}",
        f"📈 Trend: {signal['ema_trend']}"
    ]

    if signal.get("golden_cross"):
        lines.append("✨ Golden Cross (1D)")

    if signal.get("helpers"):
        lines.append("\n🧩 Destekleyiciler:")
        for h in signal["helpers"]:
            lines.append(f"• {h}")

    if signal.get("resistance_1h") or signal.get("resistance_4h"):
        lines.append("\n📍 Dirençler:")
        if signal.get("resistance_1h"):
            lines.append(f"• 1H: {signal['resistance_1h']}")
        if signal.get("resistance_4h"):
            lines.append(f"• 4H: {signal['resistance_4h']}")

    lines.append(f"\n⏰ {signal['time']}")
    return "\n".join(lines)

# ======================================================
# BULK
# ======================================================

def process_signals(data):
    out = []
    for item in data:
        try:
            out.extend(process_symbol_signals(item))
        except Exception:
            continue
    return out
