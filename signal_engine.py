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
            return True, "⚔️ Golden Cross", {}
        if all([ma20, ma50, ma100, ma200]) and ma20 > ma50 > ma100 > ma200:
            return True, "Uptrend", {}
    return False, "", {}

# ==================================================
# L2 / L3 / L4 SİNYALLER
# ==================================================
def l2_signal(item):
    # Basit orta trend kontrolü
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15:
        return None
    if tf15.get("rsi") > 55 and tf15.get("ema20") > tf15.get("ema50"):
        return ("L2-"+item["symbol"], f"L2 Sinyali: {item['symbol']}", {"type":"l2","level":"L2"})
    return None

def l3_signal(item):
    tf5 = item.get("tf", {}).get("5m", {})
    if not tf5:
        return None
    if tf5.get("rsi") > 50 and tf5.get("ema20") > tf5.get("ema50"):
        return ("L3-"+item["symbol"], f"L3 Sinyali: {item['symbol']}", {"type":"l3","level":"L3"})
    return None

def l4_signal(item):
    # OB reaction ile L4 mantığı
    tf15 = item.get("tf", {}).get("15m", {})
    df = tf15.get("df")
    if df is None:
        return None
    # OB mantığı basitleştirilmiş, detaylar aşağıda
    return order_block_reaction_signal(item)

# ==================================================
# ORDER BLOCK (L4 – SMART MONEY)
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
            "volume_ratio": round(c["volume"] / vol_avg.iloc[i], 2)
        }
    return None

def detect_ob_reaction(df, ob):
    if df is None or ob is None or len(df) < 5:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev["low"] <= ob["high"] * 1.01 and last["close"] > prev["high"] and last["close"] > last["open"]:
        return True
    return False

def order_block_reaction_signal(item):
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
    if not detect_ob_reaction(df, ob):
        return None
    strength = min(100, int(60 + ob["volume_ratio"] * 15))
    register_signal(symbol, price)
    set_cooldown(symbol, 45)
    msg = (
        f"⚡ OB REACTION + L4\n\n"
        f"Hisse: {symbol}\n"
        f"Fiyat: {fmt_price(price)}\n"
        f"OB: {fmt_price(ob['low'])} – {fmt_price(ob['high'])}\n"
        f"Trend: {trend_type}\n"
        f"Güç: %{strength}"
    )
    return (f"OBR-{symbol}", msg, {"type": "order_block", "strength": strength, "level":"L4"})

# ==================================================
# KOMBİNE VE SÜPER KOMBİNE (ÖRNEK)
# ==================================================
def combined_signal(item):
    # Basit örnek: RSI ve EMA50 kesişimi
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15:
        return None
    if tf15.get("rsi") < 30 and tf15.get("ema20") > tf15.get("ema50"):
        return ("COMB-"+item["symbol"], f"Kombine Sinyal: {item['symbol']}", {"type":"kombine","level":"Kombine"})
    return None

def super_combined_signal(item):
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15:
        return None
    if tf15.get("rsi") < 25 and tf15.get("ema20") > tf15.get("ema50") > tf15.get("ema100"):
        return ("SUPER-"+item["symbol"], f"Süper Kombine Sinyal: {item['symbol']}", {"type":"super_kombine","level":"Süper Kombine"})
    return None

# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    # Tüm algoritmalar burada çalışır
    for fn in [combined_signal, super_combined_signal, l2_signal, l3_signal, l4_signal]:
        sig = fn(item)
        if sig:
            out.append(sig)
    return out

# ==================================================
# SAFE PROCESS
# ==================================================
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
