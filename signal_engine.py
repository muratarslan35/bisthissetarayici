import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from utils import (
    nearest_support_resistance_from_history,
    detect_support_resistance_break,
    detect_three_peaks,
    to_tr_timezone
)

# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
sent_signals = {}

TARGET_PCT = 0.02
REPEAT_BLOCK_MINUTES = 45

# ==================================================
# TIME
# ==================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_repeat_block(symbol, algo):
    t = sent_signals.get((symbol, algo))
    return t and now_tr() < t

def mark_sent(symbol, algo):
    sent_signals[(symbol, algo)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

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

# ==================================================
# HELPERS
# ==================================================
def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

def trend_direction(ema20, ema50, ema200):
    if ema20 and ema50 and ema200:
        if ema20 > ema50 > ema200:
            return "📈 YUKARI"
        if ema20 < ema50 < ema200:
            return "📉 AŞAĞI"
    return "➖ YATAY"

def decide_action(strength, rsi, ema_trend):
    if strength >= 80 and rsi is not None and rsi < 35 and ema_trend == "📈 YUKARI":
        return "GÜÇLÜ AL"
    return "TAKİP ET"

# ==================================================
# META ENRICH (JSON SAFE)
# ==================================================
def enrich_meta(item, tf, base):
    ema20 = tf.get("ema20")
    ema50 = tf.get("ema50")
    ema200 = tf.get("ema200")

    ema_trend = trend_direction(ema20, ema50, ema200)
    rsi = tf.get("rsi")

    base.update({
        "symbol": item["symbol"],
        "current_price": fmt(item.get("current_price")),
        "rsi": fmt(rsi),
        "ema20": fmt(ema20),
        "ema50": fmt(ema50),
        "ema200": fmt(ema200),
        "ema_trend": ema_trend,
        "volume": fmt(tf.get("volume")),
        "volume_avg": fmt(tf.get("volume_avg_20")),
        "signal_time": now_tr().strftime("%H:%M:%S"),
        "action": decide_action(base["strength"], rsi, ema_trend)
    })
    return base

# ==================================================
# SIGNALS
# ==================================================
def combined_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf["rsi"] < 30 and not in_repeat_block(item["symbol"], "kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "kombine")
        return enrich_meta(item, tf, {
            "type": "KOMBİNE",
            "emoji": "🧠",
            "strength": 70
        })

def super_combined_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf["rsi"] < 25 and not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "super_kombine")
        return enrich_meta(item, tf, {
            "type": "SÜPER KOMBİNE",
            "emoji": "🚀",
            "strength": 90
        })

def pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf.get("ema20") and tf.get("ema50"):
        if tf["rsi"] < 40 and tf["ema20"] > tf["ema50"] and not in_repeat_block(item["symbol"], "pullback"):
            mark_sent(item["symbol"], "pullback")
            return enrich_meta(item, tf, {
                "type": "PULLBACK",
                "emoji": "🔄",
                "strength": 60
            })

def strong_pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf["rsi"] < 25 and not in_repeat_block(item["symbol"], "strong_pullback"):
        mark_sent(item["symbol"], "strong_pullback")
        return enrich_meta(item, tf, {
            "type": "GÜÇLÜ PULLBACK",
            "emoji": "💪",
            "strength": 85
        })

def three_peak_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    df = tf.get("df")
    if df is not None and detect_three_peaks(df["Close"]):
        if not in_repeat_block(item["symbol"], "three_peak"):
            mark_sent(item["symbol"], "three_peak")
            return enrich_meta(item, tf, {
                "type": "3’LÜ TEPE KIRILIMI",
                "emoji": "📉➡️📈",
                "strength": 80
            })

def support_resistance_break_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    df = tf.get("df")
    if df is None:
        return None

    _, r_break = detect_support_resistance_break(df)
    sup, res = nearest_support_resistance_from_history(df)

    if r_break and not in_repeat_block(item["symbol"], "resistance_break"):
        mark_sent(item["symbol"], "resistance_break")
        return enrich_meta(item, tf, {
            "type": "DİRENÇ KIRILIMI",
            "emoji": "🚧",
            "strength": 75,
            "support": fmt(sup),
            "resistance": fmt(res)
        })

def l2_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 55 and not in_repeat_block(item["symbol"], "l2"):
        mark_sent(item["symbol"], "l2")
        return enrich_meta(item, tf, {
            "type": "L2 TREND",
            "emoji": "📈",
            "strength": 55
        })

def l3_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 60 and not in_repeat_block(item["symbol"], "l3"):
        mark_sent(item["symbol"], "l3")
        return enrich_meta(item, tf, {
            "type": "L3 GÜÇLÜ TREND",
            "emoji": "🔥",
            "strength": 65
        })

def l4_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi", 50) > 65 and not in_repeat_block(item["symbol"], "l4"):
        mark_sent(item["symbol"], "l4")
        return enrich_meta(item, tf, {
            "type": "L4 SMART MONEY",
            "emoji": "💎",
            "strength": 75
        })

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
# MARKET KAPALI – GÜÇLÜ HİSSELER
# ==================================================
def scan_strong_stocks(data):
    out = []
    for i in data:
        tf = i.get("tf", {}).get("1d", {})
        if tf.get("ema50") and tf.get("ema200") and tf["ema50"] > tf["ema200"]:
            out.append(f"• {i['symbol']}")
    return out[:10]

# ==================================================
# GÜN SONU BAŞARI ÖZETİ
# ==================================================
def daily_success_summary():
    today = now_tr().date()
    d = success_tracker.get(today)
    if not d:
        return None

    total = len(d)
    hit = sum(1 for x in d.values() if x.get("hit"))
    fail = total - hit

    return {
        "date": str(today),
        "total": total,
        "hit": hit,
        "fail": fail,
        "success_rate": round((hit / total) * 100, 2) if total else 0
    }

# ==================================================
# TELEGRAM FORMAT
# ==================================================
def format_signal_message(symbol, signals):
    if not signals:
        return None

    s0 = signals[0]
    lines = [
        f"📈 {symbol}",
        f"💰 Fiyat: {s0.get('current_price', '-')}",
        f"📊 RSI: {s0.get('rsi', '-')}",
        f"📐 EMA20 / EMA50 / EMA200: "
        f"{s0.get('ema20','-')} / {s0.get('ema50','-')} / {s0.get('ema200','-')}",
        f"📉 EMA Trend: {s0.get('ema_trend','-')}",
        f"⏱ Saat: {s0.get('signal_time','-')}",
        "",
    ]

    for s in signals:
        lines.append(
            f"{s.get('emoji','⚡')} {s['type']} | Güç: %{s['strength']} | {s.get('action','')}"
        )
        if s.get("support"):
            lines.append(f"🟢 Destek: {s['support']}")
        if s.get("resistance"):
            lines.append(f"🔴 Direnç: {s['resistance']}")

    return "\n".join(lines)
