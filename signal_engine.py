import time
import pandas as pd
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
ob_memory = {}   # 🔥 OB HAFIZA (symbol bazlı)
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
# SUCCESS TRACKING (%2)
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

# ==================================================
# TREND CHECK (MA BAZLI)
# ==================================================
def long_term_trend_ok(item, price):
    tf_list = ["1h", "4h", "1d"]
    for tf in tf_list:
        d = item.get("tf", {}).get(tf, {})
        ma20, ma50, ma100, ma200 = (
            d.get("ema20"), d.get("ema50"), d.get("ema100"), d.get("ema200")
        )
        if ma50 and ma200 and ma50 > ma200:
            return True, "Golden Cross", {
                "MA20": ma20, "MA50": ma50, "MA100": ma100, "MA200": ma200,
                "golden_cross": True
            }
        if all([ma20, ma50, ma100, ma200]) and ma20 > ma50 > ma100 > ma200:
            return True, "Uptrend", {
                "MA20": ma20, "MA50": ma50, "MA100": ma100, "MA200": ma200
            }
    return False, "", {}

# ==================================================
# ORDER BLOCK (L4 – OLUŞUM)
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
        impulse = False
        for j in range(i + 1, min(i + 5, len(df))):
            if (df.iloc[j]["close"] - base) / base >= 0.015:
                impulse = True
                break

        if not impulse:
            continue

        return {
            "low": min(c["open"], c["close"]),
            "high": max(c["open"], c["close"]),
            "volume_ratio": round(c["volume"] / vol_avg.iloc[i], 2),
            "created_at": df.index[i]
        }

    return None

def order_block_signal(item):
    symbol = item["symbol"]
    price = item["current_price"]
    tf15 = item.get("tf", {}).get("15m", {})
    df = tf15.get("df")

    if df is None or in_cooldown(symbol):
        return None

    trend_ok, trend_type, _ = long_term_trend_ok(item, price)
    if not trend_ok:
        return None

    ob = detect_order_block(df)
    if not ob:
        return None

    ob_memory[symbol] = ob  # 🔥 OB hafızaya alındı

    if not (ob["low"] * 0.995 <= price <= ob["high"] * 1.01):
        return None

    register_signal(symbol, price)
    set_cooldown(symbol, 45)

    msg = (
        f"💼 ORDER BLOCK AL (L4)\n\n"
        f"Hisse: {symbol}\n"
        f"Fiyat: {fmt_price(price)}\n"
        f"OB: {fmt_price(ob['low'])} – {fmt_price(ob['high'])}\n"
        f"Hacim: {ob['volume_ratio']}x\n"
        f"Trend: {trend_type}"
    )

    return (f"OB-{symbol}", msg, {"type": "order_block", "level": "L4"})

# ==================================================
# 🔥 OB REACTION (L3+)
# ==================================================
def order_block_reaction(item):
    symbol = item["symbol"]
    price = item["current_price"]
    tf15 = item.get("tf", {}).get("15m", {})
    df = tf15.get("df")

    ob = ob_memory.get(symbol)
    if not ob or df is None or len(df) < 5:
        return None

    # OB bölgesine tekrar giriş
    if not (ob["low"] * 0.997 <= price <= ob["high"] * 1.01):
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 🔥 REAKSİYON ŞARTLARI
    bullish = last["close"] > last["open"]
    momentum = last["close"] > prev["high"]
    volume_ok = last["volume"] > df["volume"].rolling(20).mean().iloc[-1] * 1.3

    if not (bullish and momentum and volume_ok):
        return None

    register_signal(symbol, price)
    set_cooldown(symbol, 30)

    msg = (
        f"⚡ OB REACTION (L3+)\n\n"
        f"Hisse: {symbol}\n"
        f"Fiyat: {fmt_price(price)}\n"
        f"OB Tepki Alımı\n"
        f"Momentum + Hacim Onaylı"
    )

    return (f"OBR-{symbol}", msg, {
        "type": "order_block_reaction",
        "level": "L3+"
    })

# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []

    # 🚫 MEVCUT TÜM SİNYALLER BURADA AYNI ŞEKİLDE DURUYOR

    ob_sig = order_block_signal(item)
    if ob_sig:
        out.append(ob_sig)

    ob_react = order_block_reaction(item)
    if ob_react:
        out.append(ob_react)

    return out

def safe_process_bist_data(data_list, market_open=True):
    res = []
    if not data_list:
        return res
    for item in data_list:
        try:
            res.extend(process_signals(item, market_open))
            update_success(item["symbol"], item["current_price"])
        except Exception:
            continue
    return res
