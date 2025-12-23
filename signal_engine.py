import time
from datetime import datetime, timezone, timedelta
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
        f"%2 Hedefe Ulaşan: {hit}\n"
        f"Başarısız: {total-hit}"
    )

# ==================================================
# HELPERS
# ==================================================
def enrich_meta(item, tf, base):
    """
    Dashboard + Telegram için tüm verileri
    ÜST SEVİYEYE çıkarır
    """
    base.update({
        "current_price": item.get("current_price"),
        "price": item.get("current_price"),
        "rsi": tf.get("rsi"),
        "ema20": tf.get("ema20"),
        "ema50": tf.get("ema50"),
        "ema200": tf.get("ema200"),
        "volume": tf.get("volume"),
        "volume_avg": tf.get("volume_avg"),
        "trend_up": tf.get("trend_up", 0),
        "trend_down": tf.get("trend_down", 0),
        "tf": tf
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
        return ("kombine", "", enrich_meta(item, tf, {
            "type": "kombine",
            "symbol": item["symbol"],
            "strength": 70
        }))

def super_combined_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf["rsi"] < 25 and not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "super_kombine")
        return ("super_kombine", "", enrich_meta(item, tf, {
            "type": "super_kombine",
            "symbol": item["symbol"],
            "strength": 90
        }))

def pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf.get("ema20") and tf.get("ema50"):
        if tf["rsi"] < 40 and tf["ema20"] > tf["ema50"] and not in_repeat_block(item["symbol"], "pullback"):
            mark_sent(item["symbol"], "pullback")
            return ("pullback", "", enrich_meta(item, tf, {
                "type": "pullback",
                "symbol": item["symbol"],
                "strength": 60
            }))

def strong_pullback_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi") and tf["rsi"] < 25 and not in_repeat_block(item["symbol"], "strong_pullback"):
        mark_sent(item["symbol"], "strong_pullback")
        return ("strong_pullback", "", enrich_meta(item, tf, {
            "type": "strong_pullback",
            "symbol": item["symbol"],
            "strength": 85
        }))

def three_peak_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    df = tf.get("df")
    if df is not None and detect_three_peaks(df["Close"]):
        if not in_repeat_block(item["symbol"], "three_peak"):
            mark_sent(item["symbol"], "three_peak")
            return ("three_peak", "", enrich_meta(item, tf, {
                "type": "three_peak",
                "symbol": item["symbol"],
                "strength": 80
            }))

def support_resistance_break_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    df = tf.get("df")
    if df is None:
        return None

    s_break, r_break = detect_support_resistance_break(df)
    sup, res = nearest_support_resistance_from_history(df)

    if r_break and not in_repeat_block(item["symbol"], "resistance_break"):
        mark_sent(item["symbol"], "resistance_break")
        return ("resistance_break", "", enrich_meta(item, tf, {
            "type": "resistance_break",
            "symbol": item["symbol"],
            "strength": 75,
            "support": sup,
            "resistance": res
        }))

def l2_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 55 and not in_repeat_block(item["symbol"], "l2"):
        mark_sent(item["symbol"], "l2")
        return ("l2", "", enrich_meta(item, tf, {
            "type": "l2",
            "symbol": item["symbol"],
            "strength": 55
        }))

def l3_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi", 50) > 60 and not in_repeat_block(item["symbol"], "l3"):
        mark_sent(item["symbol"], "l3")
        return ("l3", "", enrich_meta(item, tf, {
            "type": "l3",
            "symbol": item["symbol"],
            "strength": 65
        }))

def l4_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi", 50) > 65 and not in_repeat_block(item["symbol"], "l4"):
        mark_sent(item["symbol"], "l4")
        return ("l4", "", enrich_meta(item, tf, {
            "type": "l4",
            "symbol": item["symbol"],
            "strength": 75
        }))

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
# TELEGRAM FORMAT (DETAYLI)
# ==================================================
def format_signal_message(symbol, signals, tf_data=None):
    lines = [f"📈 {symbol}"]

    price = signals[0].get("current_price")
    if price:
        lines.append(f"💰 Fiyat: {price}")

    rsi = signals[0].get("rsi")
    if rsi is not None:
        lines.append(f"📊 RSI: {round(rsi,1)}")

    if signals[0].get("ema20") and signals[0].get("ema50"):
        lines.append(f"📐 EMA20 / EMA50: {signals[0]['ema20']} / {signals[0]['ema50']}")

    if signals[0].get("volume"):
        lines.append(f"📦 Hacim: {signals[0]['volume']}")

    for s in signals:
        icon = "🔥" if s["strength"] >= 80 else "⚡"
        lines.append(f"{icon} {s['type'].upper()} | Güç: %{s['strength']}")
        if s.get("support"):
            lines.append(f"🟢 Destek: {s['support']}")
        if s.get("resistance"):
            lines.append(f"🔴 Direnç: {s['resistance']}")

    return "\n".join(lines)
