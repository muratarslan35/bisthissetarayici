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
# TREND CHECK (EMA / GOLDEN CROSS)
# ==================================================
def long_term_trend_ok(item, price):
    for tf in ["1h", "4h", "1d"]:
        d = item.get("tf", {}).get(tf, {})
        ma20 = d.get("ema20")
        ma50 = d.get("ema50")
        ma100 = d.get("ema100")
        ma200 = d.get("ema200")

        if ma50 and ma200 and ma50 > ma200:
            return True, "Golden Cross", {}

        if all([ma20, ma50, ma100, ma200]) and ma20 > ma50 > ma100 > ma200:
            return True, "Strong Uptrend", {}

    return False, "", {}

# ==================================================
# ORDER BLOCK (L4)
# ==================================================
def detect_order_block(df):
    if df is None or len(df) < 30:
        return None

    vol_avg = df["Volume"].rolling(20).mean()

    for i in range(len(df) - 5, 10, -1):
        c = df.iloc[i]

        if c["Close"] >= c["Open"]:
            continue

        if c["Volume"] < vol_avg.iloc[i] * 1.8:
            continue

        base = c["Close"]
        impulse = False
        for j in range(i + 1, min(i + 6, len(df))):
            if (df.iloc[j]["Close"] - base) / base >= 0.015:
                impulse = True
                break

        if impulse:
            return {
                "low": min(c["Open"], c["Close"]),
                "high": max(c["Open"], c["Close"]),
                "volume_ratio": round(c["Volume"] / vol_avg.iloc[i], 2)
            }

    return None

def detect_ob_reaction(df, ob):
    if df is None or ob is None or len(df) < 3:
        return False

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return (
        prev["Low"] <= ob["high"] * 1.01 and
        last["Close"] > prev["High"] and
        last["Close"] > last["Open"]
    )

# ==================================================
# OB + TREND SİNYALİ
# ==================================================
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
    if not ob or not detect_ob_reaction(df, ob):
        return None

    register_signal(symbol, price)
    set_cooldown(symbol, 45)

    return (
        f"OB-{symbol}",
        (
            f"⚡ OB + TREND\n\n"
            f"Hisse: {symbol}\n"
            f"Fiyat: {fmt_price(price)}\n"
            f"OB: {fmt_price(ob['low'])} – {fmt_price(ob['high'])}\n"
            f"Trend: {trend_type}"
        ),
        {
            "symbol": symbol,
            "price": price,
            "type": "order_block",
            "level": "L4",
            "trend": trend_type,
            "strength": int(60 + ob["volume_ratio"] * 15)
        }
    )

# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []

    ob_sig = order_block_reaction_signal(item)
    if ob_sig:
        out.append(ob_sig)

    return out

# ==================================================
# ✅ APP.PY'NİN BEKLEDİĞİ FONKSİYON
# ==================================================
def safe_process_bist_data(data_list, market_open=True):
    results = []

    if not data_list:
        return results

    for item in data_list:
        try:
            signals = process_signals(item, market_open)
            results.extend(signals)
            update_success(item["symbol"], item["current_price"])
        except Exception:
            continue

    return results

# ==================================================
# PİYASA KAPALI – GÜÇLÜLER
# ==================================================
def scan_strong_stocks(data):
    out = []
    for item in data:
        ok, _, _ = long_term_trend_ok(item, item.get("current_price"))
        if ok:
            out.append(f"• {item['symbol']}")
    return out[:10]
