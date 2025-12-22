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
# ORDER BLOCK (L4 – SMART MONEY)
# ==================================================
def detect_order_block(df):
    if df is None or len(df) < 30:
        return None

    vol_avg = df["volume"].rolling(20).mean()

    for i in range(len(df) - 5, 10, -1):
        c = df.iloc[i]

        # Son kırmızı mum
        if c["close"] >= c["open"]:
            continue

        # Hacim filtresi
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
            "volume_ratio": round(c["volume"] / vol_avg.iloc[i], 2)
        }
    return None

def order_block_signal(item):
    symbol = item["symbol"]
    price = item["current_price"]
    tf15 = item.get("tf", {}).get("15m", {})
    df = tf15.get("df")

    if df is None or in_cooldown(symbol):
        return None

    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None

    ob = detect_order_block(df)
    if not ob:
        return None

    if not (ob["low"] * 0.995 <= price <= ob["high"] * 1.01):
        return None

    strength = min(100, int(30 + ob["volume_ratio"] * 20 + 30))

    register_signal(symbol, price)
    set_cooldown(symbol, 45)

    msg = (
        f"💼 ORDER BLOCK AL (L4)\n\n"
        f"Hisse: {symbol}\n"
        f"Fiyat: {fmt_price(price)}\n"
        f"OB: {fmt_price(ob['low'])} – {fmt_price(ob['high'])}\n"
        f"Hacim: {ob['volume_ratio']}x\n"
        f"Trend: {trend_type}\n"
        f"Güç: %{strength}"
    )

    return (f"OB-{symbol}", msg, {"type": "order_block", "strength": strength})

# ==================================================
# PROCESS SIGNALS (MEVCUTLAR + OB)
# ==================================================
def process_signals(item, market_open=True):
    out = []

    # ⛔ BURADA MEVCUT TÜM SİNYALLERİN ÇAĞRILDIĞINI VARSAYIYORUZ
    # (pullback, güçlü dönüş, kombine, süper kombine vs.)

    ob_sig = order_block_signal(item)
    if ob_sig:
        out.append(ob_sig)

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

# ==================================================
# PİYASA KAPALI – GÜÇLÜ HİSSELER
# ==================================================
def scan_strong_stocks(data):
    strong = []
    for i in data:
        ok, _, _ = long_term_trend_ok(i, i.get("current_price"))
        if ok:
            strong.append(f"• {i['symbol']}")
    return strong[:10]
