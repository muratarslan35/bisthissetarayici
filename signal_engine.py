import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from fetch_bist import (
    fetch_bist_data,
    nearest_support_resistance_from_history,
    calculate_ema,
    to_tr_timezone,
    FALLBACK_SYMBOLS,
    calculate_rsi,
    detect_three_peaks
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
    if not t:
        return False
    return now_tr() < t

def set_cooldown(symbol, minutes=COOLDOWN_MINUTES):
    cooldowns[symbol] = now_tr() + timedelta(minutes=minutes)

def clear_cooldown(symbol):
    cooldowns.pop(symbol, None)

# ==================================================
# RSI HELPER (UPDATED)
# ==================================================
def rsi_ok(rsi):
    return rsi is not None and 20 <= rsi <= 80

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
        return None
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
        "",
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
def ma_direction(ma_current, ma_prev):
    if ma_current is None or ma_prev is None:
        return ""
    return "↑" if ma_current > ma_prev else "↓"

def volume_ok(tf15):
    v = tf15.get("volume")
    avg = tf15.get("volume_avg_5")
    if not v or not avg:
        return False, None
    return v > avg, {"volume": v, "avg": avg}

# ==================================================
# LONG TERM TREND CHECK
# ==================================================
def long_term_trend_ok(item, price):
    tf_list = [
        ("1h", item.get("tf", {}).get("1h", {})),
        ("4h", item.get("tf", {}).get("4h", {})),
        ("1d", item.get("tf", {}).get("1d", {}))
    ]
    for name, tf in tf_list:
        ma20 = tf.get("ema20")
        ma50 = tf.get("ema50")
        ma100 = tf.get("ema100")
        ma200 = tf.get("ema200")
        if not all([ma20, ma50, ma100, ma200]):
            continue
        golden = ma50 > ma200
        trend = ma20 > ma50 > ma100 > ma200
        if trend or golden:
            return True, "⚔️ Golden Cross" if golden else "↑ Uptrend", {
                "MA20": ma20,
                "MA50": ma50,
                "MA100": ma100,
                "MA200": ma200,
                "golden_cross": golden
            }
    return False, "", {}

# ==================================================
# MESSAGE BUILDING
# ==================================================
def fmt_ma_dict(ma_dict):
    lines = []
    for k in ["MA20", "MA50", "MA100", "MA200"]:
        v = ma_dict.get(k)
        lines.append(f"{k}: {fmt_price(v) if v else 'N/A'}")
    if ma_dict.get("golden_cross"):
        lines.append("⚔️ Golden Cross")
    return "\n".join(lines)

def fmt_nearest_sr(item):
    price = item.get("current_price")
    txt = "📍 Yakın Seviyeler:\n"
    for tf in ["1h", "4h", "1d"]:
        r = item.get(f"nearest_resistance_{tf}")
        if r:
            txt += f"• Direnç {tf.upper()}: {fmt_price(r)}\n"
            if price and (r - price) / price < 0.01:
                txt += "⚠️ Direnç çok yakın (riskli)\n"
    s = item.get("nearest_support")
    if s:
        txt += f"• Destek: {fmt_price(s)}\n"
    return txt.strip()

def build_signal_message(item, title, trend_type, ma_dict):
    return (
        f"Hisse: {item['symbol']}\n"
        f"{title}\n\n"
        f"Fiyat: {fmt_price(item.get('current_price'))} | "
        f"RSI: {item.get('RSI'):.2f}\n\n"
        f"MA Değerleri:\n{fmt_ma_dict(ma_dict)}\n"
        f"Trend: {trend_type}\n\n"
        f"{fmt_nearest_sr(item)}"
    )

# ==================================================
# SIGNAL DETECTORS (ALL BUY + %2 REGISTER)
# ==================================================
def detect_pullback_buy(item):
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15.get("last_green"):
        return None
    price = item.get("current_price")
    rsi = item.get("RSI")
    if not rsi_ok(rsi):
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    vol_ok, _ = volume_ok(tf15)
    if not vol_ok:
        return None
    register_signal(item["symbol"], price)
    set_cooldown(item["symbol"])
    return (
        "PULL-" + item["symbol"],
        build_signal_message(item, "⚡ PULLBACK AL", trend_type, ma_dict),
        {"type": "pullback"}
    )

def detect_trend_breakout_buy(item):
    if not item.get("resistance_break"):
        return None
    price = item.get("current_price")
    rsi = item.get("RSI")
    if not rsi_ok(rsi):
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    register_signal(item["symbol"], price)
    set_cooldown(item["symbol"])
    return (
        "TREND-" + item["symbol"],
        build_signal_message(item, "🧱 TREND + KIRILIM AL", trend_type, ma_dict),
        {"type": "trend_breakout"}
    )

def detect_three_peak_break_buy(item):
    if not item.get("three_peak_break"):
        return None
    price = item.get("current_price")
    rsi = item.get("RSI")
    if not rsi_ok(rsi):
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    register_signal(item["symbol"], price)
    set_cooldown(item["symbol"])
    return (
        "3PEAK-" + item["symbol"],
        build_signal_message(item, "🔥 3'LÜ TEPE KIRILIMI AL", trend_type, ma_dict),
        {"type": "three_peak_break"}
    )

# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    for detector in [
        detect_pullback_buy,
        detect_trend_breakout_buy,
        detect_three_peak_break_buy
    ]:
        sig = detector(item)
        if sig:
            out.append(sig)
    return out

# ==================================================
# SAFE PROCESS
# ==================================================
def safe_process_bist_data(data_list, market_open=True):
    results = []
    for item in data_list or []:
        try:
            for tf_name in ["1h", "4h", "1d"]:
                tf = item.get("tf", {}).get(tf_name, {})
                df = tf.get("df")
                if df is not None and not df.empty:
                    ns, nr = nearest_support_resistance_from_history(df)
                    item[f"nearest_resistance_{tf_name}"] = nr
                    item["nearest_support"] = ns
            results.extend(process_signals(item, market_open))
        except Exception:
            continue
    return results
