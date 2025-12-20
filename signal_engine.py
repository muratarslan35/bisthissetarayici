import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from fetch_bist import (
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

def in_cooldown(key):
    t = cooldowns.get(key)
    return t and now_tr() < t

def set_cooldown(key, minutes=COOLDOWN_MINUTES):
    cooldowns[key] = now_tr() + timedelta(minutes=minutes)

def clear_cooldown(key):
    cooldowns.pop(key, None)

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
        return False
    d["last_price"] = price
    if not d["hit"] and price >= d["target"]:
        d["hit"] = True
    return d["hit"]

def daily_success_summary():
    today = now_tr().date()
    day = success_tracker.get(today)
    if not day:
        return None
    total = len(day)
    success = sum(1 for d in day.values() if d["hit"])
    lines = [
        "📊 GÜN SONU SİNYAL ÖZETİ",
        f"Toplam: {total}",
        f"Başarılı (%2): {success}",
        f"Başarısız: {total - success}",
        ""
    ]
    for s, d in day.items():
        lines.append(
            f"{s} {'✅' if d['hit'] else '❌'} "
            f"{fmt_price(d['entry'])} → {fmt_price(d['last_price'])}"
        )
    return "\n".join(lines)

# ==================================================
# TECH HELPERS
# ==================================================
def volume_ok(tf15):
    v = tf15.get("volume")
    avg = tf15.get("volume_avg_5")
    if not v or not avg:
        return False, None
    return v > avg, {"volume": v, "avg": avg}

def long_term_trend_ok(item, price):
    for tf_name in ["1h", "4h", "1d"]:
        tf = item.get("tf", {}).get(tf_name, {})
        ma20, ma50, ma100, ma200 = (
            tf.get("ema20"),
            tf.get("ema50"),
            tf.get("ema100"),
            tf.get("ema200"),
        )
        if not all([ma20, ma50, ma100, ma200]):
            continue
        golden = ma50 > ma200
        trend = ma20 > ma50 > ma100 > ma200
        if trend or golden:
            return True, ("⚔️ Golden Cross" if golden else "📈 Uptrend"), {
                "MA20": ma20, "MA50": ma50,
                "MA100": ma100, "MA200": ma200,
                "golden_cross": golden
            }
    return False, "", {}

# ==================================================
# MESSAGE HELPERS
# ==================================================
def fmt_nearest_sr(item):
    price = item.get("current_price")
    txt = "📍 Yakın Seviyeler:\n"
    ns = item.get("nearest_support")
    for tf in ["1h", "4h", "1d"]:
        nr = item.get(f"nearest_resistance_{tf}")
        if nr:
            txt += f"• Direnç {tf.upper()}: {fmt_price(nr)}\n"
            if price and (nr - price) / price < 0.01:
                txt += "⚠️ Direnç çok yakın (riskli)\n"
    if ns:
        txt += f"• Destek: {fmt_price(ns)}\n"
    return txt.strip()

def build_signal_message(item, title, trend_type, ma_dict):
    price = item.get("current_price")
    rsi = item.get("RSI")
    tf15 = item.get("tf", {}).get("15m", {})
    vol_ok, vol = volume_ok(tf15)
    vol_txt = f"{vol['volume']} / Ort: {vol['avg']}" if vol else "N/A"

    return (
        f"Hisse: {item['symbol']}\n"
        f"{title}\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n"
        f"Hacim: {vol_txt}\n"
        f"Trend: {trend_type}\n\n"
        f"{fmt_nearest_sr(item)}"
    )

# ==================================================
# SIGNAL DETECTORS (ALIM)
# ==================================================
def detect_pullback_buy(item):
    symbol = item["symbol"]
    tf15 = item.get("tf", {}).get("15m", {})
    price = item.get("current_price")
    rsi = item.get("RSI")

    if not tf15.get("last_green"):
        return None
    if rsi < 20 or rsi > 80:
        return None
    if in_cooldown(symbol):
        return None

    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    vol_ok, _ = volume_ok(tf15)

    if trend_ok and vol_ok:
        register_signal(symbol, price)
        set_cooldown(symbol)
        msg = build_signal_message(item, "⚡ PULLBACK AL", trend_type, ma_dict)
        return ("PULL-" + symbol, msg, {"type": "buy"})
    return None

def detect_trend_breakout_buy(item):
    symbol = item["symbol"]
    price = item.get("current_price")
    rsi = item.get("RSI")

    if not item.get("resistance_break"):
        return None
    if rsi < 20 or rsi > 80:
        return None
    if in_cooldown(symbol):
        return None

    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    tf15 = item.get("tf", {}).get("15m", {})
    vol_ok, _ = volume_ok(tf15)

    if trend_ok and vol_ok:
        register_signal(symbol, price)
        set_cooldown(symbol)
        msg = build_signal_message(item, "🧱 TREND + DİRENÇ KIRILIMI AL", trend_type, ma_dict)
        return ("TREND-" + symbol, msg, {"type": "buy"})
    return None

# ==================================================
# PROCESS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    if not market_open:
        return out

    for detector in [
        detect_pullback_buy,
        detect_trend_breakout_buy,
    ]:
        sig = detector(item)
        if sig:
            out.append(sig)

    return out

def safe_process_bist_data(data_list, market_open=True):
    results = []
    if not data_list:
        return results

    for item in data_list:
        try:
            for tf_name in ["1h", "4h", "1d"]:
                df = item.get("tf", {}).get(tf_name, {}).get("df")
                if df is not None and not df.empty:
                    _, nr = nearest_support_resistance_from_history(df)
                    item[f"nearest_resistance_{tf_name}"] = nr

            results.extend(process_signals(item, market_open))
            update_success(item["symbol"], item.get("current_price"))

        except Exception:
            continue

    return results

# ==================================================
# MARKET CLOSED – STRONG STOCKS
# ==================================================
def scan_strong_stocks(data_list, limit=5):
    strong = []

    for item in data_list:
        try:
            price = item.get("current_price")
            rsi = item.get("RSI")
            if not price or not rsi:
                continue
            if rsi < 20 or rsi > 80:
                continue

            trend_ok, trend_type, _ = long_term_trend_ok(item, price)
            tf15 = item.get("tf", {}).get("15m", {})
            vol_ok, _ = volume_ok(tf15)

            if trend_ok and vol_ok:
                strong.append(
                    f"• {item['symbol']} | {fmt_price(price)} | RSI {rsi:.1f} | {trend_type}"
                )

        except Exception:
            continue

    return strong[:limit]
