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
        f"Başarılı: {success}",
        f"Başarısız: {total - success}",
        "",
    ]
    for s, d in day.items():
        lines.append(f"{s} {'✅' if d['hit'] else '❌'} {fmt_price(d['entry'])} → {fmt_price(d['last_price'])}")
    return "\n".join(lines)

# ==================================================
# TECH HELPERS
# ==================================================
def ma_direction(ma_current, ma_prev):
    if ma_current is None or ma_prev is None:
        return "N/A"
    return "↑" if ma_current > ma_prev else "↓"

def trend_ma_ok(tf):
    try:
        ma20 = tf.get("ema20")
        ma50 = tf.get("ema50")
        ma100 = tf.get("ema100")
        ma200 = tf.get("ema200")
        if not all([ma20, ma50, ma100, ma200]):
            return False, None
        golden = ma50 > ma200
        trend = ma20 > ma50 > ma100 > ma200
        return (trend or golden), {"MA20": ma20, "MA50": ma50, "MA100": ma100, "MA200": ma200, "golden_cross": golden}
    except Exception:
        return False, None

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
    trend_ok = False
    trend_type = ""
    ma_dict = {}
    tf_list = [("1h", item.get("tf", {}).get("1h", {})),
               ("4h", item.get("tf", {}).get("4h", {})),
               ("1d", item.get("tf", {}).get("1d", {}))]
    for name, tf in tf_list:
        ma20 = tf.get("ema20")
        ma50 = tf.get("ema50")
        ma100 = tf.get("ema100")
        ma200 = tf.get("ema200")
        ma_dict = {"MA20": ma20, "MA50": ma50, "MA100": ma100, "MA200": ma200}
        price_over_ma = any([ma and price > ma for ma in ma_dict.values() if ma])
        golden_cross = ma50 and ma200 and ma50 > ma200
        ma_dict["golden_cross"] = golden_cross
        if price_over_ma or golden_cross:
            trend_ok = True
            trend_type = "⚔️ Golden Cross" if golden_cross else "↑ Uptrend"
            break
    return trend_ok, trend_type, ma_dict

# ==================================================
# MESSAGE BUILDING
# ==================================================
def fmt_ma_dict(ma_dict, prev_ma_dict=None):
    lines = []
    for k, v in ma_dict.items():
        if k != "golden_cross" and v is not None:
            dir_sym = ""
            if prev_ma_dict and prev_ma_dict.get(k) is not None:
                dir_sym = ma_direction(v, prev_ma_dict.get(k))
            lines.append(f"{k}: {fmt_price(v)} {dir_sym}")
    # Golden Cross durumu varsa ekle
    if ma_dict.get("golden_cross"):
        lines.append("⚔️ Golden Cross oluştu")
    # Alt alta yazdır
    return "\n".join(lines)

def fmt_nearest_sr(item):
    ns = item.get("nearest_support")
    nr1h = item.get("nearest_resistance_1h")
    nr4h = item.get("nearest_resistance_4h")
    nr1d = item.get("nearest_resistance_1d")
    txt = ""
    if ns or nr1h or nr4h or nr1d:
        txt += "📍 Yakın Seviyeler:\n"
        if ns:
            txt += f"• Destek: {fmt_price(ns)}\n"
        if nr1h:
            txt += f"• Direnç 1H: {fmt_price(nr1h)}\n"
        if nr4h:
            txt += f"• Direnç 4H: {fmt_price(nr4h)}\n"
        if nr1d:
            txt += f"• Direnç 1D: {fmt_price(nr1d)}\n"
        price = item.get("current_price")
        for nr in [nr1h, nr4h, nr1d]:
            if nr and price and (nr - price)/price < 0.01:
                txt += "⚠️ Direnç çok yakın (riskli)\n"
    else:
        txt = "📍 Yakın destek / direnç yok"
    return txt.strip()

def build_signal_message(item, sig_name, sig_type, trend_type, ma_dict, bonus_text=""):
    price = item.get("current_price")
    rsi = item.get("RSI")
    tf15 = item.get("tf", {}).get("15m", {})
    vol_ok, vol_data = volume_ok(tf15)
    vol_text = f"{vol_data['volume']} (Ort: {vol_data['avg']})" if vol_data else "N/A"
    msg = (
        f"Hisse: {item['symbol']}\n"
        f"{sig_name}\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n"
        f"Hacim: {vol_text}\n"
        f"MA Değerleri:\n{fmt_ma_dict(ma_dict)}\n"
        f"Trend: {trend_type}\n\n"
        f"{fmt_nearest_sr(item)}"
    )
    if bonus_text:
        msg += f"\n\n+ BONUS: {bonus_text}"
    return msg

# ==================================================
# SIGNAL DETECTORS
# ==================================================
def detect_pullback_buy(item):
    tf15 = item.get("tf", {}).get("15m", {})
    symbol = item["symbol"]
    price = item.get("current_price")
    rsi = item.get("RSI")
    
    if not tf15.get("last_green"):
        return None
    
    cooldown_key = f"{symbol}_pullback"
    if in_cooldown(cooldown_key):
        return None
    
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    
    if not rsi or rsi < 50 or rsi > 70:
        return None
    
    vol_ok, vol_data = volume_ok(tf15)
    if not vol_ok:
        return None
    
    ma20 = ma_dict.get("MA20")
    ma50 = ma_dict.get("MA50")
    if ma20 and price > ma20 * 1.02:
        return None
    if ma50 and price > ma50 * 1.02:
        return None
    
    set_cooldown(cooldown_key)
    
    msg = build_signal_message(item, "⚡️ PULLBACK AL", "pullback", trend_type, ma_dict)
    return (f"PULL-{symbol}", msg, {"type": "pullback"})

def detect_super_combined(item, market_open=True):
    if not item.get("super_combined_ok") or not market_open:
        return None
    symbol = item["symbol"]
    price = item.get("current_price")
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if in_cooldown(symbol):
        return None
    register_signal(symbol, price)
    set_cooldown(symbol)
    msg = build_signal_message(item, "🚀🚀🚀 SÜPER KOMBİNE", "super", trend_type, ma_dict)
    return (f"SUPER-{symbol}", msg, {"type": "super"})

def detect_trend_breakout_buy(item):
    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None
    if not item.get("resistance_break"):
        return None
    tf15 = item.get("tf", {}).get("15m", {})
    rsi = item.get("RSI")
    if not rsi or rsi < 50 or rsi > 70:
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, item.get("current_price"))
    if not trend_ok:
        return None
    vol_ok, vol_data = volume_ok(tf15)
    if not vol_ok:
        return None
    price = item.get("current_price")
    nr1h = item.get("nearest_resistance_1h")
    nr4h = item.get("nearest_resistance_4h")
    nr1d = item.get("nearest_resistance_1d")
    for nr in [nr1h, nr4h, nr1d]:
        if nr and (nr - price)/price < 0.01:
            return None
    set_cooldown(symbol)
    msg = build_signal_message(item, "🧱 TREND + KIRILIM AL", "trend_breakout", trend_type, ma_dict)
    return (f"TREND-{symbol}", msg, {"type": "trend_breakout"})

# ==================================================
# KOMBİNE SİNYAL (YENİ MANTIK)
# ==================================================
def detect_kombine_buy(item, market_open=True):
    symbol = item["symbol"]
    tf1d = item.get("tf", {}).get("1d", {})
    tf4h = item.get("tf", {}).get("4h", {})
    tf1h = item.get("tf", {}).get("1h", {})

    # 1 Günlük şartlar
    yesterday_green = tf1d.get("prev_green")          
    today_open_green = tf1d.get("first_candle_green") 
    if not (yesterday_green and today_open_green):
        return None

    # 4 Saatlik şart
    if not tf4h.get("last_green"):
        return None

    # 1 Saatlik şart
    if not tf1h.get("last_green"):
        return None

    cooldown_key = f"{symbol}_kombine"
    if in_cooldown(cooldown_key):
        return None

    price = item.get("current_price")
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)

    bonus = []
    rsi = item.get("RSI")
    if rsi and 50 <= rsi <= 70:
        bonus.append("RSI uygun")
    if trend_ok:
        bonus.append("MA uygun")

    bonus_text = ", ".join(bonus) if bonus else ""

    msg = build_signal_message(item, "🚀 KOMBİNE SİNYAL TESPİT EDİLDİ", "kombine", trend_type, ma_dict, bonus_text)

    set_cooldown(cooldown_key)

    return ("KOMB-" + symbol, msg, {"type": "kombine"})

def detect_three_peak_break_buy(item):
    if not item.get("three_peak_break"):
        return None
    symbol = item["symbol"]
    price = item.get("current_price")
    rsi = item.get("RSI")
    tf15 = item.get("tf", {}).get("15m", {})
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    vol_ok, vol_data = volume_ok(tf15)
    rsi_ok = rsi and 50 <= rsi <= 70
    if trend_ok and vol_ok and rsi_ok:
        set_cooldown(symbol)
        msg = build_signal_message(item, "🔥 3 LU TEPE KIRILIMI AL", "three_peak_break", trend_type, ma_dict)
        return ("3PEAK-" + symbol, msg, {"type": "three_peak_break"})
    return None

# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    for detector in [
        detect_pullback_buy,
        lambda i: detect_super_combined(i, market_open),
        detect_trend_breakout_buy,
        lambda i: detect_kombine_buy(i, market_open),
        detect_three_peak_break_buy
    ]:
        sig = detector(item)
        if sig:
            out.append(sig)
    return out

# ==================================================
# SAFE FETCH ALL BIST DATA AND PROCESS
# ==================================================
def safe_process_bist_data(data_list, market_open=True):
    results = []
    if not data_list:
        return results
    for item in data_list:
        try:
            for tf_name, tf in [("1h", item.get("tf", {}).get("1h", {})),
                                ("4h", item.get("tf", {}).get("4h", {})),
                                ("1d", item.get("tf", {}).get("1d", {}))]:
                df = tf.get("df")
                if df is not None and not df.empty:
                    ns, nr = nearest_support_resistance_from_history(df)
                    item[f"nearest_resistance_{tf_name}"] = nr
            results.extend(process_signals(item, market_open))
        except Exception:
            continue
    return results
