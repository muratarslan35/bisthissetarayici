# signal_engine.py
import time
from datetime import datetime, timezone, timedelta
from utils import nearest_support_resistance_from_history, to_tr_timezone

success_tracker = {}
cooldowns = {}
TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30

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

def register_signal(symbol, price):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
        }

def long_term_trend_ok(item):
    for tf in ["1h", "4h", "1d"]:
        d = item.get("tf", {}).get(tf, {})
        e20, e50, e100, e200 = (
            d.get("ema20"), d.get("ema50"),
            d.get("ema100"), d.get("ema200")
        )
        if e50 and e200 and e50 > e200:
            return True, "Golden Cross"
        if all([e20, e50, e100, e200]) and e20 > e50 > e100 > e200:
            return True, "Strong Uptrend"
    return False, ""

def detect_order_block(df):
    if df is None or len(df) < 30:
        return None
    vol_avg = df["Volume"].rolling(20).mean()
    for i in range(len(df)-5, 10, -1):
        c = df.iloc[i]
        if c["Close"] >= c["Open"]:
            continue
        if c["Volume"] < vol_avg.iloc[i] * 1.8:
            continue
        base = c["Close"]
        for j in range(i+1, min(i+5, len(df))):
            if (df.iloc[j]["Close"] - base) / base >= 0.015:
                return {
                    "low": min(c["Open"], c["Close"]),
                    "high": max(c["Open"], c["Close"]),
                    "volume_ratio": round(c["Volume"] / vol_avg.iloc[i], 2)
                }
    return None

def detect_ob_reaction(df, ob):
    if df is None or ob is None or len(df) < 2:
        return False
    prev, last = df.iloc[-2], df.iloc[-1]
    return (
        prev["Low"] <= ob["high"] * 1.01 and
        last["Close"] > prev["High"] and
        last["Close"] > last["Open"]
    )

def order_block_signal(item):
    symbol = item["symbol"]
    price = item["current_price"]
    tf15 = item["tf"].get("15m") or item["tf"].get("30m")
    df = tf15.get("df") if tf15 else None

    if df is None or in_cooldown(symbol):
        return None

    trend_ok, trend_type = long_term_trend_ok(item)
    if not trend_ok:
        return None

    ob = detect_order_block(df)
    if not ob or not detect_ob_reaction(df, ob):
        return None

    register_signal(symbol, price)
    set_cooldown(symbol)

    return (
        f"OB-{symbol}",
        f"""
⚡ OB + TREND SİNYALİ

Hisse: {symbol}
Fiyat: {fmt_price(price)}
OB: {fmt_price(ob['low'])} – {fmt_price(ob['high'])}
Trend: {trend_type}

RSI: {tf15.get('rsi')}
EMA20/50/100/200:
{fmt_price(tf15.get('ema20'))} /
{fmt_price(tf15.get('ema50'))} /
{fmt_price(tf15.get('ema100'))} /
{fmt_price(tf15.get('ema200'))}
""",
        {"type": "order_block"}
    )

def process_signals(item, market_open=True):
    out = []
    ob = order_block_signal(item)
    if ob:
        out.append(ob)
    return out
