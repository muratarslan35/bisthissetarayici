from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

from utils import (
    calculate_rsi,
    moving_averages,
    detect_support_resistance_break,
    detect_three_peaks,
    to_tr_timezone
)

# ======================================================
# GLOBAL AYARLAR
# ======================================================

TARGET_PCT = 0.015          # %1.5 başarı hedefi
REPEAT_BLOCK_MIN = 45       # aynı sinyal tekrar süresi (dk)

# ======================================================
# HAFIZA & STATE
# ======================================================

signal_memory = defaultdict(lambda: {
    "helpers": set(),
    "first_seen": None,
    "main_signal": None,
    "entry_price": None,
    "target": None,
    "success": False
})

sent_block = {}  # (symbol, signal_type) -> datetime

# ======================================================
# TIME
# ======================================================

def now_tr():
    return to_tr_timezone(datetime.utcnow())

def in_block(symbol, signal_type):
    t = sent_block.get((symbol, signal_type))
    return t and now_tr() < t

def mark_block(symbol, signal_type):
    sent_block[(symbol, signal_type)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MIN)

# ======================================================
# YARDIMCI ALGORTİMALAR
# ======================================================

def l2_pullback(df):
    return df["Close"].iloc[-1] > df["Low"].rolling(10).min().iloc[-1]

def l3_impulse(df):
    return df["Close"].iloc[-1] > df["Close"].rolling(20).mean().iloc[-1]

def l4_trend_expand(df):
    return df["Close"].iloc[-1] > df["High"].rolling(50).mean().iloc[-1]

def order_block(df):
    body = abs(df["Close"] - df["Open"])
    return body.iloc[-1] > body.rolling(20).mean().iloc[-1] * 1.6

def kurumsal_order_block(df):
    return df["Volume"].iloc[-1] > df["Volume"].rolling(20).mean().iloc[-1] * 2

def volume_confirm(df):
    return df["Volume"].iloc[-1] > df["Volume"].rolling(20).mean().iloc[-1] * 1.4

def squeeze_break(df):
    high = df["High"].rolling(20).max()
    low = df["Low"].rolling(20).min()
    width = (high - low) / high
    return width.iloc[-2] < 0.04 and df["Close"].iloc[-1] > high.iloc[-2]

def triangle_break(df):
    highs = df["High"].rolling(5).max()
    return df["Close"].iloc[-1] > highs.iloc[-2]

def triple_top_break(df):
    return detect_three_peaks(df["Close"])

# ======================================================
# TREND DOĞRULAMA
# ======================================================

def trend_confirm(rsi, ema20, ema50):
    return rsi > 50 and ema20 > ema50

def strong_trend(rsi, ema20, ema50, ema200):
    return rsi > 55 and ema20 > ema50 > ema200

# ======================================================
# ANA MANTIK
# ======================================================

def process_symbol(symbol, df15):
    """
    df15: 15m dataframe (hayali mum uygulanmış olmalı)
    """

    if df15 is None or len(df15) < 60:
        return None

    price = df15["Close"].iloc[-1]
    rsi = calculate_rsi(df15["Close"]).iloc[-1]
    emas = moving_averages(df15, [20, 50, 200])

    ema20 = emas[20]
    ema50 = emas[50]
    ema200 = emas[200]

    helpers = set()

    # ---------------------------
    # YARDIMCILARI TOPLA
    # ---------------------------

    if l2_pullback(df15): helpers.add("l2")
    if l3_impulse(df15): helpers.add("l3")
    if l4_trend_expand(df15): helpers.add("l4")
    if order_block(df15): helpers.add("ob")
    if kurumsal_order_block(df15): helpers.add("kurumsal_ob")
    if volume_confirm(df15): helpers.add("volume")
    if squeeze_break(df15): helpers.add("squeeze")
    if triangle_break(df15): helpers.add("triangle")
    if triple_top_break(df15): helpers.add("triple_top")

    mem = signal_memory[symbol]

    if not mem["first_seen"]:
        mem["first_seen"] = now_tr()

    mem["helpers"].update(helpers)

    # ==================================================
    # SÜPER KOMBİNE
    # ==================================================

    if (
        {"l3", "ob", "volume", "squeeze"}.issubset(mem["helpers"])
        and strong_trend(rsi, ema20, ema50, ema200)
        and not in_block(symbol, "super_kombine")
    ):
        mem["main_signal"] = "SÜPER KOMBİNE"
        mem["entry_price"] = price
        mem["target"] = price * (1 + TARGET_PCT)
        mark_block(symbol, "super_kombine")
        return build_signal(symbol, mem, price, rsi, "🚀")

    # ==================================================
    # KOMBİNE
    # ==================================================

    if (
        {"l2", "l3"}.issubset(mem["helpers"])
        and trend_confirm(rsi, ema20, ema50)
        and not in_block(symbol, "kombine")
    ):
        mem["main_signal"] = "KOMBİNE"
        mem["entry_price"] = price
        mem["target"] = price * (1 + TARGET_PCT)
        mark_block(symbol, "kombine")
        return build_signal(symbol, mem, price, rsi, "🧠")

    # ==================================================
    # YARDIMCIDAN GÜÇLÜ AL'A EVRİLEN
    # ==================================================

    if (
        {"squeeze", "triangle"}.intersection(mem["helpers"])
        and {"volume", "ob"}.intersection(mem["helpers"])
        and strong_trend(rsi, ema20, ema50, ema200)
        and not in_block(symbol, "guclu_al")
    ):
        mem["main_signal"] = "GÜÇLÜ AL"
        mem["entry_price"] = price
        mem["target"] = price * (1 + TARGET_PCT)
        mark_block(symbol, "guclu_al")
        return build_signal(symbol, mem, price, rsi, "🔥")

    return None

# ======================================================
# SİNYAL ÇIKTI
# ======================================================

def build_signal(symbol, mem, price, rsi, emoji):
    return {
        "symbol": symbol,
        "signal": mem["main_signal"],
        "emoji": emoji,
        "price": round(price, 2),
        "target": round(mem["target"], 2),
        "rsi": round(rsi, 1),
        "helpers": sorted(list(mem["helpers"])),
        "first_seen": mem["first_seen"].strftime("%H:%M:%S"),
        "time": now_tr().strftime("%H:%M:%S"),
        "success": mem["success"]
    }

# ======================================================
# BAŞARI TAKİBİ
# ======================================================

def update_success(symbol, current_price):
    mem = signal_memory.get(symbol)
    if mem and mem["target"] and not mem["success"]:
        if current_price >= mem["target"]:
            mem["success"] = True
