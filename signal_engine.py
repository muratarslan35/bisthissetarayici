import time
from datetime import datetime, timezone, timedelta
from utils import (
    nearest_support_resistance_from_history,
    to_tr_timezone
)

# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
cooldowns = {}
TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30

# ==================================================
# TIME HELPERS
# ==================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)

def in_cooldown(symbol):
    t = cooldowns.get(symbol)
    return t and now_tr() < t

def set_cooldown(symbol, minutes=COOLDOWN_MINUTES):
    cooldowns[symbol] = now_tr() + timedelta(minutes=minutes)

# ==================================================
# SUCCESS TRACKING
# ==================================================
def register_signal(symbol, price):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "last_price": price,
        }

def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if not d:
        return
    d["last_price"] = price
    if not d["hit"] and price >= d["target"]:
        d["hit"] = True

def daily_success_summary():
    today = now_tr().date()
    d = success_tracker.get(today)
    if not d:
        return None
    total = len(d)
    success = sum(1 for x in d.values() if x["hit"])
    return (
        "📊 GÜN SONU ÖZET\n\n"
        f"Toplam AL: {total}\n"
        f"%2 Başarılı: {success}\n"
        f"Başarısız: {total - success}"
    )

# ==================================================
# TREND + GOLDEN CROSS
# ==================================================
def long_term_trend_ok(item, price):
    tf_list = ["1h", "4h", "1d"]
    for tf in tf_list:
        d = item.get("tf", {}).get(tf, {})
        ma20 = d.get("ema20")
        ma50 = d.get("ema50")
        ma100 = d.get("ema100")
        ma200 = d.get("ema200")

        if ma50 and ma200 and ma50 > ma200:
            return True, "Golden Cross", {
                "ema20": ma20, "ema50": ma50, "ema100": ma100, "ema200": ma200
            }

        if all([ma20, ma50, ma100, ma200]) and ma20 > ma50 > ma100 > ma200:
            return True, "Strong Uptrend", {
                "ema20": ma20, "ema50": ma50, "ema100": ma100, "ema200": ma200
            }

    return False, "", {}

# ==================================================
# ORDER BLOCK (L4)
# ==================================================
def detect_order_block(df):
    if df is None or len(df) < 30:
        return None

    vol_avg = df["volume"].rolling(20).mean()

    for i in range(len(df) - 5, 10, -1):
        c = df.iloc[i]
        if c["close"] >= c["open"]:
            continue
        if c["volume"] < vol_avg.iloc[i] * 1.8:
            continue

        base = c["close"]
        for j in range(i + 1, min(i + 5, len(df))):
            if (df.iloc[j]["close"] - base) / base >= 0.015:
                return {
                    "low": min(c["open"], c["close"]),
                    "high": max(c["open"], c["close"]),
                    "volume_ratio": round(c["volume"] / vol_avg.iloc[i], 2)
                }
    return None

def detect_ob_reaction(df, ob):
    if df is None or ob is None or len(df) < 5:
        return False

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return (
        prev["low"] <= ob["high"] * 1.01 and
        last["close"] > prev["high"] and
        last["close"] > last["open"]
    )

# ==================================================
# OB + KOMBINASYON
# ==================================================
def order_block_reaction_signal(item):
    symbol = item["symbol"]
    price = item["current_price"]
    tf15 = item.get("tf", {}).get(item.get("used_timeframe", "15m"), {})
    df = tf15.get("df")

    if df is None or in_cooldown(symbol):
        return None

    trend_ok, trend_type, emas = long_term_trend_ok(item, price)
    if not trend_ok:
        return None

    ob = detect_order_block(df)
    if not ob or not detect_ob_reaction(df, ob):
        return None

    register_signal(symbol, price)
    set_cooldown(symbol, 45)

    ns, nr = nearest_support_resistance_from_history(df)

    meta = {
        "symbol": symbol,
        "price": price,
        "type": "order_block",
        "title": "OB + Trend + Momentum",
        "direction": "up",
        "level": "L4",
        "strength": min(100, int(60 + ob["volume_ratio"] * 15)),
        "rsi": tf15.get("rsi"),
        "ema20": emas.get("ema20"),
        "ema50": emas.get("ema50"),
        "ema100": emas.get("ema100"),
        "ema200": emas.get("ema200"),
        "trend": trend_type,
        "support": ns,
        "resistance": nr
    }

    msg = (
        f"⚡ OB + L4 SİNYAL\n\n"
        f"Hisse: {symbol}\n"
        f"Fiyat: {fmt_price(price)}\n"
        f"Trend: {trend_type}\n"
        f"RSI: {fmt_price(meta['rsi'])}\n"
        f"EMA20/50/100/200: "
        f"{fmt_price(meta['ema20'])} / {fmt_price(meta['ema50'])} / "
        f"{fmt_price(meta['ema100'])} / {fmt_price(meta['ema200'])}\n"
        f"Destek / Direnç: {fmt_price(ns)} / {fmt_price(nr)}"
    )

    return (f"OB-{symbol}", msg, meta)

# ==================================================
# PROCESS
# ==================================================
def process_signals(item, market_open=True):
    out = []

    ob_sig = order_block_re
