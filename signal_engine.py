import time
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from utils import (
    nearest_support_resistance_from_history,
    detect_support_resistance_break,
    detect_three_peaks,
    detect_order_block,
    to_tr_timezone
)

# ======================================================
# GLOBAL STATE
# ======================================================
signal_state = {}
sent_signals = {}
success_tracker = {}
successful_signals_store = {}

TARGET_PCT = 0.015
REPEAT_BLOCK_MINUTES = 30

# ======================================================
# TIME
# ======================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_repeat_block(symbol, algo):
    t = sent_signals.get((symbol, algo))
    return t and now_tr() < t

def mark_sent(symbol, algo):
    sent_signals[(symbol, algo)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

# ======================================================
# SUCCESS TRACKING
# ======================================================
def register_signal(symbol, price, algo):
    if not isinstance(symbol, str) or not isinstance(price, (int, float)):
        return
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "symbol": symbol,
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "algorithm": algo,
            "time": now_tr().strftime("%H:%M:%S")
        }

def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if d and not d["hit"] and price >= d["target"]:
        d["hit"] = True
        successful_signals_store.setdefault(today, {})
        successful_signals_store[today][symbol] = d

# ======================================================
# SAFE HELPERS
# ======================================================
def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

def safe(v):
    return v if isinstance(v, (int, float)) else None

# ======================================================
# RSI
# ======================================================
def synthetic_rsi_from_df(df, current_price, period=14):
    if df is None or "Close" not in df or len(df) < period + 2:
        return None
    closes = df["Close"].iloc[-period - 1:].tolist()
    closes.append(current_price)
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if not isinstance(avg_loss, (int, float)) or avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

# ======================================================
# TREND / VOLUME
# ======================================================
def trend_direction(e20, e50, e200):
    if all(isinstance(v, (int, float)) for v in (e20, e50, e200)):
        if e20 > e50 > e200:
            return "📈 YUKARI"
        if e20 < e50 < e200:
            return "📉 AŞAĞI"
    return "➖ YATAY"

def volume_strength(v, avg):
    if not isinstance(v, (int, float)) or not isinstance(avg, (int, float)):
        return None
    r = v / avg
    if r >= 1.5:
        return "GÜÇLÜ"
    if r >= 1:
        return "ORTA"
    return "ZAYIF"

def decide_action(strength, trend, vol):
    if strength >= 8.5 and trend == "📈 YUKARI" and vol in ("ORTA", "GÜÇLÜ"):
        return "GÜÇLÜ AL"
    if strength >= 7:
        return "AL"
    return "TAKİP"

# ======================================================
# META ENRICH
# ======================================================
def enrich_meta(item, tf, base):
    tf1h = item.get("tf", {}).get("1h") or {}
    tf4h = item.get("tf", {}).get("4h") or {}

    ema_tr = trend_direction(
        tf.get("ema20"), tf.get("ema50"), tf.get("ema200")
    )

    vol_tag = volume_strength(
        tf.get("volume"), tf.get("volume_avg_20")
    )

    base.update({
        "symbol": item.get("symbol"),
        "current_price": fmt(item.get("current_price")),
        "trend_direction": ema_tr,
        "volume_tag": vol_tag,
        "rsi_1h": synthetic_rsi_from_df(tf1h.get("df"), item.get("current_price")),
        "rsi_4h": synthetic_rsi_from_df(tf4h.get("df"), item.get("current_price")),
        "resistance_1h": fmt(tf1h.get("resistance")),
        "resistance_4h": fmt(tf4h.get("resistance")),
        "time": now_tr().strftime("%H:%M:%S"),
        "success": False,
        "level_change": False,
        "strength": round(base["strength"] / 10, 1),
        "action": decide_action(base["strength"], ema_tr, vol_tag)
    })
    return base

# ======================================================
# VOLATILITY
# ======================================================
def bollinger_band_width(df, period=20):
    if df is None or len(df) < period:
        return None
    ma = df["Close"].rolling(period).mean()
    sd = df["Close"].rolling(period).std()
    v = ((ma + 2 * sd) - (ma - 2 * sd)) / ma
    return safe(v.iloc[-1])

def atr(df, period=14):
    if df is None or len(df) < period + 1:
        return None
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs()
    ], axis=1).max(axis=1)
    return safe(tr.rolling(period).mean().iloc[-1])

# ======================================================
# ALGORITHMS
# ======================================================
def l2_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    return enrich_meta(item, tf, {"type": "l2", "emoji": "🟢", "strength": 65})

def l3_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    return enrich_meta(item, tf, {"type": "l3", "emoji": "🟢", "strength": 70})

def l4_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    return enrich_meta(item, tf, {"type": "l4", "emoji": "🟢", "strength": 75})

def breakout_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    if detect_support_resistance_break(tf):
        return enrich_meta(item, tf, {"type": "breakout", "emoji": "🚀", "strength": 80})

def three_peak_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    if detect_three_peaks(tf):
        return enrich_meta(item, tf, {"type": "three_peak", "emoji": "🔺", "strength": 78})

def ob_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    if detect_order_block(tf):
        return enrich_meta(item, tf, {"type": "order_block", "emoji": "📦", "strength": 76})

def squeeze_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    df = tf.get("df")
    if df is None or len(df) < 30:
        return None

    bb = bollinger_band_width(df)
    a = atr(df)
    vol = tf.get("volume")
    vol_avg = tf.get("volume_avg_20")
    rsi = tf.get("rsi")

    is_squeeze = (
        safe(bb) is not None and bb < 0.035 and
        safe(a) is not None and
        safe(vol) is not None and safe(vol_avg) is not None and
        vol < vol_avg * 0.9 and
        isinstance(rsi, (int, float)) and 40 <= rsi <= 60
    )

    key = f"{item.get('symbol')}_squeeze"
    prev = signal_state.get(key, {})

    if not is_squeeze and prev.get("active"):
        signal_state[key] = {"active": False}
        return enrich_meta(item, tf, {"type": "squeeze_break", "emoji": "💥", "strength": 85})

    if is_squeeze:
        signal_state[key] = {"active": True}
        return enrich_meta(item, tf, {"type": "squeeze", "emoji": "🫧", "strength": 72})

def combined_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    if tf.get("rsi", 50) < 40 and detect_support_resistance_break(tf):
        return enrich_meta(item, tf, {"type": "combined", "emoji": "⚡", "strength": 88})

def super_combined_signal(item):
    tf = item.get("tf", {}).get("15m") or {}
    if tf.get("rsi", 50) < 40 and detect_support_resistance_break(tf) and detect_order_block(tf):
        return enrich_meta(item, tf, {"type": "super_combined", "emoji": "🔥", "strength": 92})

# ======================================================
# PROCESS ENGINE
# ======================================================
def process_signals(item, market_open=True):
    if not isinstance(item, dict):
        return []

    symbol = item.get("symbol")
    price = item.get("current_price")
    if not isinstance(symbol, str) or not isinstance(price, (int, float)):
        return []

    item.setdefault("tf", {})
    signals = []

    for fn in (
        l2_signal,
        l3_signal,
        l4_signal,
        breakout_signal,
        three_peak_signal,
        ob_signal,
        squeeze_signal,
        combined_signal,
        super_combined_signal
    ):
        try:
            r = fn(item)
            if isinstance(r, dict):
                signals.append(r)
        except Exception:
            continue

    if not signals:
        return []

    # --- BASE bilgiyi en güçlü algoritmadan al ---
    strongest = max(signals, key=lambda x: x["strength"])
    base = strongest.copy()

    # --- tüm algoritmaları listele ---
    base["algorithms"] = [s["type"] for s in signals]
    base["combined_algorithms"] = signals

    # --- önceki state ile karşılaştır ---
    prev = signal_state.get(symbol)
    if prev:
        added = list(set(base["algorithms"]) - set(prev["algorithms"]))
        if added:
            base["level_change"] = True
            base["added_algorithms"] = added
            base["strengthen_time"] = now_tr().strftime("%H:%M:%S")
            base["first_signal_time"] = prev["first_signal_time"]
            base["first_algorithms"] = prev["first_algorithms"]
    else:
        base["first_signal_time"] = now_tr().strftime("%H:%M:%S")
        base["first_algorithms"] = base["algorithms"]

    signal_state[symbol] = {
        "algorithms": base["algorithms"],
        "first_signal_time": base["first_signal_time"],
        "first_algorithms": base["first_algorithms"]
    }

    # --- başarı durumu ---
    today = now_tr().date()
    if today in successful_signals_store and symbol in successful_signals_store[today]:
        base["success"] = True

    register_signal(symbol, price, base["type"])
    update_success(symbol, price)

    return [base]
