import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

from utils import (
    nearest_support_resistance_from_history,
    detect_support_resistance_break,
    detect_three_peaks,
    detect_order_block,
    calculate_rsi,
    moving_averages,
    to_tr_timezone
)

# =====================================================
# GLOBAL STATE (HAFIZA & KONTROL)
# =====================================================
sent_block = {}              # tekrar engeli
signal_memory = {}           # güçlenen sinyaller
success_tracker = {}         # %1.5 başarı takibi

TARGET_PCT = 0.015
REPEAT_MIN = 45


# =====================================================
# TIME
# =====================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))


def in_repeat(symbol, key):
    t = sent_block.get((symbol, key))
    return t and now_tr() < t


def mark_repeat(symbol, key):
    sent_block[(symbol, key)] = now_tr() + timedelta(minutes=REPEAT_MIN)


# =====================================================
# SUCCESS TRACKING (%1.5)
# =====================================================
def register_success(symbol, price, algo):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "symbol": symbol,
            "entry": price,
            "target": round(price * (1 + TARGET_PCT), 2),
            "hit": False,
            "algorithm": algo,
            "time": now_tr().strftime("%H:%M:%S")
        }


def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if d and not d["hit"] and price >= d["target"]:
        d["hit"] = True


# =====================================================
# CORE HELPERS
# =====================================================
def ema_trend(tf):
    e20, e50, e200 = tf.get("ema20"), tf.get("ema50"), tf.get("ema200")
    if e20 and e50 and e200:
        if e20 > e50 > e200:
            return "YUKARI"
        if e20 < e50 < e200:
            return "AŞAĞI"
    return "YATAY"


def volume_tag(v, avg):
    if not v or not avg:
        return "ZAYIF"
    if v > avg * 1.5:
        return "GÜÇLÜ"
    if v > avg:
        return "ORTA"
    return "ZAYIF"


def action_from_strength(strength):
    if strength >= 8.5:
        return "GÜÇLÜ AL"
    if strength >= 7:
        return "AL"
    return "TAKİP"


# =====================================================
# BASE META BUILDER (TEK STANDART)
# =====================================================
def build_meta(item, tf, base):
    tf1h = item["tf"].get("1h", {})
    tf4h = item["tf"].get("4h", {})

    trend = ema_trend(tf)
    vol = volume_tag(tf.get("volume"), tf.get("volume_avg_20"))

    base.update({
        "symbol": item["symbol"],
        "price": round(item["current_price"], 2),
        "time": now_tr().strftime("%H:%M:%S"),
        "trend": trend,
        "ema_trend": trend,
        "volume": vol,

        "rsi_15m": tf.get("rsi"),
        "rsi_1h": calculate_rsi(tf1h.get("df", pd.DataFrame())["Close"]).iloc[-1]
        if tf1h.get("df") is not None else None,
        "rsi_4h": calculate_rsi(tf4h.get("df", pd.DataFrame())["Close"]).iloc[-1]
        if tf4h.get("df") is not None else None,

        "strength": round(base["strength"], 1),
        "signal": action_from_strength(base["strength"]),
        "success": False
    })

    return base


# =====================================================
# ALGORITHMS (YARDIMCILAR)
# =====================================================
def l2(item):
    tf = item["tf"]["5m"]
    if tf["rsi"] > 50 and not in_repeat(item["symbol"], "l2"):
        mark_repeat(item["symbol"], "l2")
        return build_meta(item, tf, {
            "type": "L2",
            "emoji": "📈",
            "strength": 6.8
        })


def l3(item):
    tf = item["tf"]["5m"]
    if tf["rsi"] > 55 and not in_repeat(item["symbol"], "l3"):
        mark_repeat(item["symbol"], "l3")
        return build_meta(item, tf, {
            "type": "L3",
            "emoji": "🔥",
            "strength": 7.4
        })


def l4(item):
    tf = item["tf"]["15m"]
    if tf["rsi"] > 60 and not in_repeat(item["symbol"], "l4"):
        mark_repeat(item["symbol"], "l4")
        return build_meta(item, tf, {
            "type": "L4",
            "emoji": "💎",
            "strength": 8.0
        })


def order_block_signal(item):
    tf = item["tf"]["15m"]
    if detect_order_block(tf["df"]) and not in_repeat(item["symbol"], "ob"):
        register_success(item["symbol"], item["current_price"], "OB")
        mark_repeat(item["symbol"], "ob")
        return build_meta(item, tf, {
            "type": "ORDER_BLOCK",
            "emoji": "🧱",
            "strength": 8.6
        })


def three_peak_break(item):
    tf = item["tf"]["15m"]
    if detect_three_peaks(tf["df"]["Close"]) and not in_repeat(item["symbol"], "3peak"):
        mark_repeat(item["symbol"], "3peak")
        return build_meta(item, tf, {
            "type": "ÜÇLÜ_TEPE_KIRILIM",
            "emoji": "📉➡️📈",
            "strength": 8.2
        })


def breakout(item):
    tf = item["tf"]["15m"]
    _, r = detect_support_resistance_break(tf["df"])
    if r and not in_repeat(item["symbol"], "breakout"):
        mark_repeat(item["symbol"], "breakout")
        return build_meta(item, tf, {
            "type": "DİRENÇ_KIRILIM",
            "emoji": "🚧",
            "strength": 8.1
        })


# =====================================================
# KOMBİNE & SUPER KOMBİNE
# =====================================================
def kombine(item):
    tf15 = item["tf"]["15m"]
    tf4h = item["tf"]["4h"]

    if (
        tf15["rsi"] < 40 and
        ema_trend(tf4h) == "YUKARI" and
        not in_repeat(item["symbol"], "kombine")
    ):
        register_success(item["symbol"], item["current_price"], "KOMBİNE")
        mark_repeat(item["symbol"], "kombine")
        return build_meta(item, tf15, {
            "type": "KOMBİNE",
            "emoji": "🧠",
            "strength": 8.5
        })


def super_kombine(item):
    tf15 = item["tf"]["15m"]
    tf1h = item["tf"]["1h"]
    tf4h = item["tf"]["4h"]

    if (
        tf15["rsi"] < 35 and
        ema_trend(tf1h) == "YUKARI" and
        ema_trend(tf4h) == "YUKARI" and
        not in_repeat(item["symbol"], "super")
    ):
        register_success(item["symbol"], item["current_price"], "SUPER")
        mark_repeat(item["symbol"], "super")
        return build_meta(item, tf15, {
            "type": "SUPER_KOMBİNE",
            "emoji": "🚀",
            "strength": 9.2
        })


# =====================================================
# PROCESS SIGNALS (ANA MOTOR)
# =====================================================
def process_signals(item, market_open=True):
    signals = []

    for fn in (
        l2, l3, l4,
        breakout,
        three_peak_break,
        order_block_signal,
        kombine,
        super_kombine
    ):
        r = fn(item)
        if r:
            signals.append(r)

    if not signals:
        return []

    main = max(signals, key=lambda x: x["strength"])
    main["helpers"] = [s["type"] for s in signals if s["type"] != main["type"]]

    prev = signal_memory.get(item["symbol"])
    if prev:
        added = list(set(main["helpers"]) - set(prev["helpers"]))
        if added:
            main["level_change"] = True
            main["new_helpers"] = added
            main["first_seen"] = prev["first_seen"]
        else:
            main["level_change"] = False
            main["first_seen"] = prev["first_seen"]
    else:
        main["first_seen"] = main["time"]
        main["level_change"] = False

    today = now_tr().date()
    if today in success_tracker and item["symbol"] in success_tracker[today]:
        if success_tracker[today][item["symbol"]]["hit"]:
            main["success"] = True

    signal_memory[item["symbol"]] = {
        "helpers": main["helpers"],
        "first_seen": main["first_seen"]
    }

    return [main]


# =====================================================
# MESSAGE FORMAT (TELEGRAM + DASHBOARD)
# =====================================================
def format_signal_message(s):
    return (
        f"{s['emoji']} {s['symbol']} — {s['signal']}\n"
        f"Fiyat: {s['price']}\n"
        f"Güç: {s['strength']}\n"
        f"Trend: {s['trend']} | Hacim: {s['volume']}\n"
        f"RSI 15m / 1h / 4h: {s['rsi_15m']} / {s['rsi_1h']} / {s['rsi_4h']}\n"
        f"Ana: {s['type']}\n"
        f"Yardımcılar: {', '.join(s['helpers']) if s['helpers'] else '-'}\n"
        f"İlk: {s['first_seen']} | Şimdi: {s['time']}"
    )
