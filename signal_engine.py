import time
from datetime import datetime, timezone, timedelta
from utils import (
    nearest_support_resistance_from_history,
    detect_support_resistance_break,
    detect_three_peaks,
    calculate_rsi,
    to_tr_timezone
)

# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
cooldowns = {}
sent_signals = {}   # (symbol, algo) -> last_ts

TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30
REPEAT_BLOCK_MINUTES = 45

# ==================================================
# TIME
# ==================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_repeat_block(symbol, algo):
    key = (symbol, algo)
    t = sent_signals.get(key)
    return t and now_tr() < t

def mark_sent(symbol, algo):
    sent_signals[(symbol, algo)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

def set_cooldown(symbol, minutes=COOLDOWN_MINUTES):
    cooldowns[symbol] = now_tr() + timedelta(minutes=minutes)

def in_cooldown(symbol):
    t = cooldowns.get(symbol)
    return t and now_tr() < t

# ==================================================
# SUCCESS TRACK
# ==================================================
def register_signal(symbol, price):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False
        }

def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if d and not d["hit"] and price >= d["target"]:
        d["hit"] = True

def daily_success_summary():
    today = now_tr().date()
    d = success_tracker.get(today)
    if not d:
        return None
    total = len(d)
    hit = sum(1 for x in d.values() if x["hit"])
    return (
        "📊 GÜN SONU ÖZET\n\n"
        f"Toplam AL: {total}\n"
        f"%2 Başarılı: {hit}\n"
        f"Başarısız: {total-hit}"
    )

# ==================================================
# KOMBİNE
# ==================================================
def combined_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    rsi = tf.get("rsi")
    if rsi and rsi < 30 and not in_repeat_block(item["symbol"], "kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "kombine")
        return ("kombine", "", {
            "type": "kombine",
            "symbol": item["symbol"],
            "strength": 70
        })

def super_combined_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    rsi = tf.get("rsi")
    if rsi and rsi < 25 and not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "super_kombine")
        return ("super_kombine", "", {
            "type": "super_kombine",
            "symbol": item["symbol"],
            "strength": 90
        })

# ==================================================
# PULLBACK
# ==================================================
def pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    rsi = tf.get("rsi")
    ema20 = tf.get("ema20")
    ema50 = tf.get("ema50")

    if rsi and ema20 and ema50:
        if rsi < 40 and ema20 > ema50 and not in_repeat_block(item["symbol"], "pullback"):
            mark_sent(item["symbol"], "pullback")
            return ("pullback", "", {
                "type": "pullback",
                "symbol": item["symbol"],
                "strength": 60
            })

def strong_pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    rsi = tf.get("rsi")
    if rsi and rsi < 25 and not in_repeat_block(item["symbol"], "strong_pullback"):
        mark_sent(item["symbol"], "strong_pullback")
        return ("strong_pullback", "", {
            "type": "strong_pullback",
            "symbol": item["symbol"],
            "strength": 85
        })

# ==================================================
# 3’LÜ TEPE KIRILIMI
# ==================================================
def three_peak_signal(item):
    df = item.get("tf", {}).get("15m", {}).get("df")
    if df is not None and detect_three_peaks(df["Close"]):
        if not in_repeat_block(item["symbol"], "three_peak"):
            mark_sent(item["symbol"], "three_peak")
            return ("three_peak", "", {
                "type": "three_peak",
                "symbol": item["symbol"],
                "strength": 80
            })

# ==================================================
# DESTEK / DİRENÇ KIRILIMI
# ==================================================
def support_resistance_break_signal(item):
    df = item.get("tf", {}).get("15m", {}).get("df")
    if df is None:
        return None

    s_break, r_break = detect_support_resistance_break(df)
    sup, res = nearest_support_resistance_from_history(df)

    if r_break and not in_repeat_block(item["symbol"], "resistance_break"):
        mark_sent(item["symbol"], "resistance_break")
        return ("resistance_break", "", {
            "type": "resistance_break",
            "symbol": item["symbol"],
            "strength": 75,
            "support": sup,
            "resistance": res
        })

# ==================================================
# L2 – L3 – L4
# ==================================================
def l2_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 55 and not in_repeat_block(item["symbol"], "l2"):
        mark_sent(item["symbol"], "l2")
        return ("l2", "", {"type": "l2", "symbol": item["symbol"], "strength": 55})

def l3_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 60 and not in_repeat_block(item["symbol"], "l3"):
        mark_sent(item["symbol"], "l3")
        return ("l3", "", {"type": "l3", "symbol": item["symbol"], "strength": 65})

def l4_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi", 50) > 65 and not in_repeat_block(item["symbol"], "l4"):
        mark_sent(item["symbol"], "l4")
        return ("l4", "", {"type": "l4", "symbol": item["symbol"], "strength": 75})

# ==================================================
# PROCESS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    for fn in [
        combined_signal,
        super_combined_signal,
        pullback_signal,
        strong_pullback_signal,
        three_peak_signal,
        support_resistance_break_signal,
        l2_signal,
        l3_signal,
        l4_signal
    ]:
        r = fn(item)
        if r:
            out.append(r)
    return out

def safe_process_bist_data(data_list, market_open=True):
    res = []
    for item in data_list:
        try:
            res.extend(process_signals(item, market_open))
            update_success(item["symbol"], item["current_price"])
        except Exception:
            continue
    return res

# ==================================================
# MARKET CLOSED
# ==================================================
def scan_strong_stocks(data):
    out = []
    for i in data:
        tf = i.get("tf", {}).get("1d", {})
        if tf.get("ema50") and tf.get("ema200") and tf["ema50"] > tf["ema200"]:
            out.append(f"• {i['symbol']}")
    return out[:10]

# ==================================================
# TELEGRAM MESAJ FORMAT
# ==================================================
def format_signal_message(symbol, signals, tf_data):
    lines = []
    lines.append(f"📈 {symbol}")

    if tf_data:
        rsi = tf_data.get("rsi")
        if rsi is not None:
            lines.append(f"RSI: {rsi:.1f}")

    for s in signals:
        stype = s.get("type", "")
        strength = s.get("strength", s.get("trend_strength", 50))
        support = s.get("support")
        resistance = s.get("resistance")

        line = f"• {stype.upper()} | Güç: %{strength}"
        lines.append(line)

        if support or resistance:
            if support:
                lines.append(f"  Destek: {support}")
            if resistance:
                lines.append(f"  Direnç: {resistance}")

    return "\n".join(lines)
