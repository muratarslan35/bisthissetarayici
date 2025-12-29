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

success_tracker = {}
sent_signals = {}
successful_signals_store = {}
signal_state = {}

TARGET_PCT = 0.015
REPEAT_BLOCK_MINUTES = 45

def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_repeat_block(symbol, algo):
    t = sent_signals.get((symbol, algo))
    return t and now_tr() < t

def mark_sent(symbol, algo):
    sent_signals[(symbol, algo)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

def register_signal(symbol, price, algo_type):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "symbol": symbol,
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "algorithm": algo_type,
            "time": now_tr().strftime("%H:%M:%S")
        }

def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if d and not d["hit"] and price >= d["target"]:
        d["hit"] = True
        successful_signals_store.setdefault(today, {})
        successful_signals_store[today][symbol] = d

def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

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
    if avg_loss == 0 or np.isnan(avg_loss):
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def trend_direction(ema20, ema50, ema200):
    if ema20 and ema50 and ema200:
        if ema20 > ema50 > ema200:
            return "📈 YUKARI"
        if ema20 < ema50 < ema200:
            return "📉 AŞAĞI"
    return "➖ YATAY"

def volume_strength(vol, vol_avg):
    if not vol or not vol_avg:
        return None
    r = vol / vol_avg
    if r >= 1.5:
        return "GÜÇLÜ"
    if r >= 1.0:
        return "ORTA"
    return "ZAYIF"

def decide_action(strength, trend, vol):
    if strength >= 8.5 and trend == "📈 YUKARI" and vol in ("ORTA", "GÜÇLÜ"):
        return "GÜÇLÜ AL"
    if strength >= 7:
        return "AL"
    return "TAKİP ET"

def enrich_meta(item, tf, base):
    tf1h = item["tf"].get("1h", {})
    tf4h = item["tf"].get("4h", {})

    ema_tr = trend_direction(tf.get("ema20"), tf.get("ema50"), tf.get("ema200"))
    vol_tag = volume_strength(tf.get("volume"), tf.get("volume_avg_20"))

    base.update({
        "symbol": item["symbol"],
        "current_price": fmt(item["current_price"]),
        "ema_trend": ema_tr,
        "trend_direction": ema_tr,
        "volume_tag": vol_tag,
        "rsi_1h": synthetic_rsi_from_df(tf1h.get("df"), item["current_price"]),
        "rsi_4h": synthetic_rsi_from_df(tf4h.get("df"), item["current_price"]),
        "resistance_1h": fmt(tf1h.get("resistance")),
        "resistance_4h": fmt(tf4h.get("resistance")),
        "time": now_tr().strftime("%H:%M:%S"),
        "success": False,
        "level_change": False,
        "strength": round(base["strength"] / 10, 1),
        "action": decide_action(base["strength"], ema_tr, vol_tag),
    })
    return base

def bollinger_band_width(df, period=20, std=2):
    if df is None or len(df) < period:
        return None
    ma = df["Close"].rolling(period).mean()
    sd = df["Close"].rolling(period).std()
    upper = ma + std * sd
    lower = ma - std * sd
    return ((upper - lower) / ma).iloc[-1]

def atr(df, period=14):
    if df is None or len(df) < period + 1:
        return None
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def l2_signal(item):
    tf = item["tf"].get("5m", {})
    if tf.get("rsi", 0) > 55 and not in_repeat_block(item["symbol"], "l2"):
        mark_sent(item["symbol"], "l2")
        return enrich_meta(item, tf, {"type": "l2", "emoji": "📈", "strength": 55})

def l3_signal(item):
    tf = item["tf"].get("5m", {})
    if tf.get("rsi", 0) > 60 and not in_repeat_block(item["symbol"], "l3"):
        mark_sent(item["symbol"], "l3")
        return enrich_meta(item, tf, {"type": "l3", "emoji": "🔥", "strength": 65})

def l4_signal(item):
    tf = item["tf"].get("15m", {})
    if tf.get("rsi", 0) > 65 and not in_repeat_block(item["symbol"], "l4"):
        mark_sent(item["symbol"], "l4")
        return enrich_meta(item, tf, {"type": "l4", "emoji": "💎", "strength": 75})

def breakout_signal(item):
    tf = item["tf"].get("15m", {})
    df = tf.get("df")
    if df is None:
        return None
    _, r = detect_support_resistance_break(df)
    if r and not in_repeat_block(item["symbol"], "breakout"):
        mark_sent(item["symbol"], "breakout")
        return enrich_meta(item, tf, {"type": "breakout", "emoji": "🚧", "strength": 78})

def three_peak_signal(item):
    tf = item["tf"].get("15m", {})
    df = tf.get("df")
    if df is not None and detect_three_peaks(df["Close"]) and not in_repeat_block(item["symbol"], "three_peak"):
        mark_sent(item["symbol"], "three_peak")
        return enrich_meta(item, tf, {"type": "three_peak", "emoji": "📉➡️📈", "strength": 80})

def ob_signal(item):
    tf15 = item["tf"].get("15m", {})
    df = tf15.get("df")
    if df is None:
        return None
    if detect_order_block(df) and not in_repeat_block(item["symbol"], "ob"):
        register_signal(item["symbol"], item["current_price"], "ob")
        mark_sent(item["symbol"], "ob")
        return enrich_meta(item, tf15, {"type": "ob", "emoji": "🧱", "strength": 85})

def squeeze_signal(item):
    tf = item["tf"].get("15m", {})
    df = tf.get("df")
    if df is None or len(df) < 30:
        return None
    bb_width = bollinger_band_width(df)
    atr_val = atr(df)
    vol = tf.get("volume")
    vol_avg = tf.get("volume_avg_20")
    rsi = tf.get("rsi", 0)
    is_squeeze = (
        bb_width and bb_width < 0.035
        and atr_val
        and vol and vol_avg
        and vol < vol_avg * 0.9
        and 40 <= rsi <= 60
    )
    prev_state = signal_state.get(f"{item['symbol']}_squeeze", {})
    if not is_squeeze and prev_state.get("squeeze_active"):
        mark_sent(item["symbol"], "squeeze_break")
        meta = enrich_meta(item, tf, {"type": "squeeze_break", "emoji": "💥", "strength": 78})
        signal_state[f"{item['symbol']}_squeeze"] = {"squeeze_active": False}
        return meta
    if is_squeeze:
        signal_state[f"{item['symbol']}_squeeze"] = {"squeeze_active": True}
    if is_squeeze and not in_repeat_block(item["symbol"], "squeeze"):
        mark_sent(item["symbol"], "squeeze")
        return enrich_meta(item, tf, {"type": "squeeze", "emoji": "🫧", "strength": 72})
    return None

def combined_signal(item):
    tf15 = item["tf"].get("15m", {})
    tf1h = item["tf"].get("1h", {})
    tf4h = item["tf"].get("4h", {})
    tf1d = item["tf"].get("1d", {})
    rsi15 = tf15.get("rsi", 100)
    rsi4h = synthetic_rsi_from_df(tf4h.get("df"), item["current_price"])
    if not (
        tf1d.get("close") > tf1d.get("open")
        and tf4h.get("close") > tf4h.get("open")
        and 28 <= rsi15 <= 38
        and rsi4h and rsi4h > 55
    ):
        return None
    if not in_repeat_block(item["symbol"], "kombine"):
        register_signal(item["symbol"], item["current_price"], "kombine")
        mark_sent(item["symbol"], "kombine")
        return enrich_meta(item, tf15, {"type": "kombine", "emoji": "🧠", "strength": 75})

def super_combined_signal(item):
    tf15 = item["tf"].get("15m", {})
    tf1h = item["tf"].get("1h", {})
    tf4h = item["tf"].get("4h", {})
    tf1d = item["tf"].get("1d", {})
    rsi15 = tf15.get("rsi", 100)
    rsi1h = synthetic_rsi_from_df(tf1h.get("df"), item["current_price"])
    rsi4h = synthetic_rsi_from_df(tf4h.get("df"), item["current_price"])
    if not (
        tf1d.get("close") > tf1d.get("open")
        and tf4h.get("close") > tf4h.get("open")
        and 25 <= rsi15 <= 35
        and rsi1h and rsi1h > 55
        and rsi4h and rsi4h > 60
    ):
        return None
    if not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"], "super_kombine")
        mark_sent(item["symbol"], "super_kombine")
        return enrich_meta(item, tf15, {"type": "super_kombine", "emoji": "🚀", "strength": 90})

def process_signals(item, market_open=True):
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
        r = fn(item)
        if r:
            signals.append(r)
    if not signals:
        return []
    base = signals[0]
    base["combined_algorithms"] = signals
    base["algorithms"] = [a["type"] for a in signals]
    if base["type"] == "kombine":
        base["combined_type"] = "KOMBİNE"
    elif base["type"] == "super_kombine":
        base["combined_type"] = "SÜPER"
    else:
        base["combined_type"] = None
    prev = signal_state.get(base["symbol"])
    if prev:
        new_algos = list(set(base["algorithms"]) - set(prev["algorithms"]))
        if new_algos:
            base["level_change"] = True
            base["strengthen_time"] = now_tr().strftime("%H:%M:%S")
            base["added_algorithms"] = new_algos
            base["first_signal_time"] = prev["first_signal_time"]
            base["first_algorithms"] = prev["first_algorithms"]
    else:
        base["first_signal_time"] = now_tr().strftime("%H:%M:%S")
        base["first_algorithms"] = base["algorithms"]
    signal_state[base["symbol"]] = {
        "algorithms": base["algorithms"],
        "first_signal_time": base["first_signal_time"],
        "first_algorithms": base["first_algorithms"],
    }
    today = now_tr().date()
    if today in successful_signals_store and base["symbol"] in successful_signals_store[today]:
        base["success"] = True
    return [base]
