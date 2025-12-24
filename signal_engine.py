import time
from datetime import datetime, timezone, timedelta

from utils import (
    nearest_support_resistance_from_history,
    detect_support_resistance_break,
    detect_three_peaks,
    to_tr_timezone
)

success_tracker = {}
sent_signals = {}

TARGET_PCT = 0.015
REPEAT_BLOCK_MINUTES = 45

def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_repeat_block(symbol, algo):
    t = sent_signals.get((symbol, algo))
    return t and now_tr() < t

def mark_sent(symbol, algo):
    sent_signals[(symbol, algo)] = now_tr() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

def register_signal(symbol, price):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "algorithm": None,
            "time": now_tr().strftime("%H:%M:%S")
        }

def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if d and not d["hit"] and price >= d["target"]:
        d["hit"] = True

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
        "time": now_tr().strftime("%H:%M:%S"),
        "action": decide_action(base["strength"], rsi, ema_trend)
    })
    # Kaydı başarı tracker'a ekle
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    success_tracker[today][item["symbol"]] = {
        **success_tracker[today].get(item["symbol"], {}),
        "algorithm": base["type"],
        "entry": fmt(item.get("current_price")),
        "hit": success_tracker[today].get(item["symbol"], {}).get("hit", False),
        "time": now_tr().strftime("%H:%M:%S")
    }
    return base

# ---------------- MULTI-TIMEFRAME CONTROL ----------------
def trend_consistency_15m_1h_4h(tf_15m, tf_1h, tf_4h):
    """
    15m'de sinyal tetiklenirse, 1h ve 4h trendleri ile uyumlu mu kontrol et.
    Yukarı trend: EMA20 > EMA50 > EMA200
    Aşağı trend: EMA20 < EMA50 < EMA200
    """
    def trend(ema20, ema50, ema200):
        if ema20 and ema50 and ema200:
            if ema20 > ema50 > ema200: return "UP"
            if ema20 < ema50 < ema200: return "DOWN"
        return "NEUTRAL"

    trend_15 = trend(tf_15m.get("ema20"), tf_15m.get("ema50"), tf_15m.get("ema200"))
    trend_1h = trend(tf_1h.get("ema20"), tf_1h.get("ema50"), tf_1h.get("ema200"))
    trend_4h = trend(tf_4h.get("ema20"), tf_4h.get("ema50"), tf_4h.get("ema200"))

    if trend_15 == "UP":
        return trend_1h == "UP" and trend_4h == "UP"
    if trend_15 == "DOWN":
        return trend_1h == "DOWN" and trend_4h == "DOWN"
    return False

# ---------------- SIGNAL FUNCTIONS ----------------
def combined_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    if tf_15.get("rsi") and tf_15["rsi"] < 30 and not in_repeat_block(item["symbol"], "kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "kombine")
        return enrich_meta(item, tf_15, {"type":"kombine","emoji":"🧠","strength":70})

def super_combined_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    if tf_15.get("rsi") and tf_15["rsi"] < 25 and not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "super_kombine")
        return enrich_meta(item, tf_15, {"type":"super_kombine","emoji":"🚀","strength":90})

def pullback_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    if tf_15.get("rsi") and tf_15.get("ema20") and tf_15.get("ema50"):
        if tf_15["rsi"] < 40 and tf_15["ema20"] > tf_15["ema50"] and not in_repeat_block(item["symbol"], "pullback"):
            mark_sent(item["symbol"], "pullback")
            return enrich_meta(item, tf_15, {"type":"pullback","emoji":"🔄","strength":60})

def strong_pullback_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    if tf_15.get("rsi") and tf_15["rsi"] < 25 and not in_repeat_block(item["symbol"], "strong_pullback"):
        mark_sent(item["symbol"], "strong_pullback")
        return enrich_meta(item, tf_15, {"type":"GÜÇLÜ PULLBACK","emoji":"💪","strength":85})

def three_peak_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    df = tf_15.get("df")
    if df is not None and detect_three_peaks(df["Close"]):
        if not in_repeat_block(item["symbol"], "three_peak"):
            mark_sent(item["symbol"], "three_peak")
            return enrich_meta(item, tf_15, {"type":"three_peak","emoji":"📉➡️📈","strength":80})

def support_resistance_break_signal(item):
    tf_15 = item.get("tf", {}).get("15m", {})
    tf_1h = item.get("tf", {}).get("1h", {})
    tf_4h = item.get("tf", {}).get("4h", {})

    if not trend_consistency_15m_1h_4h(tf_15, tf_1h, tf_4h):
        return None

    df = tf_15.get("df")
    if df is None: return None
    _, r_break = detect_support_resistance_break(df)
    sup, res = nearest_support_resistance_from_history(df)
    if r_break and not in_repeat_block(item["symbol"], "resistance_break"):
        mark_sent(item["symbol"], "resistance_break")
        return enrich_meta(item, tf_15, {"type":"resistance_break","emoji":"🚧","strength":75,"support":fmt(sup),"resistance":fmt(res)})

# ---------------- L2-L3-L4 Sinyalleri (5m) ----------------
def l2_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi",50) > 55 and not in_repeat_block(item["symbol"], "l2"):
        mark_sent(item["symbol"], "l2")
        return enrich_meta(item, tf, {"type":"l2","emoji":"📈","strength":55})

def l3_signal(item):
    tf = item.get("tf", {}).get("5m", {})
    if tf.get("rsi",50) > 60 and not in_repeat_block(item["symbol"], "l3"):
        mark_sent(item["symbol"], "l3")
        return enrich_meta(item, tf, {"type":"l3","emoji":"🔥","strength":65})

def l4_signal(item):
    tf = item.get("tf", {}).get("15m", {})
    if tf.get("rsi",50) > 65 and not in_repeat_block(item["symbol"], "l4"):
        mark_sent(item["symbol"], "l4")
        return enrich_meta(item, tf, {"type":"l4","emoji":"💎","strength":75})

# ---------------- PROCESS SIGNALS WITH GROUPING ----------------
def process_signals(item, market_open=True):
    signals = []
    for fn in [
        combined_signal, super_combined_signal, pullback_signal,
        strong_pullback_signal, three_peak_signal,
        support_resistance_break_signal, l2_signal, l3_signal, l4_signal
    ]:
        r = fn(item)
        if r:
            signals.append(r)

    if signals:
        combined = signals[0].copy()
        combined["combined_algorithms"] = [
            {
                "type": s["type"],
                "emoji": s.get("emoji","⚡"),
                "strength": s.get("strength"),
                "action": s.get("action"),
                "support": s.get("support"),
                "resistance": s.get("resistance"),
                "time": s.get("time")
            } for s in signals
        ]
        return [combined]
    return []

def safe_process_bist_data(data_list, market_open=True):
    res=[]
    for item in data_list:
        try:
            processed = process_signals(item, market_open)
            if processed:
                res.extend(processed)
            update_success(item["symbol"], item["current_price"])
        except Exception:
            continue
    return res

def scan_strong_stocks(data):
    out=[]
    for i in data:
        tf=i.get("tf",{}).get("1d",{})
        if tf.get("ema50") and tf.get("ema200") and tf["ema50"]>tf["ema200"]:
            out.append(f"• {i['symbol']}")
    return out[:10]

def daily_success_summary(include_details=False, max_failures=0):
    today=now_tr().date()
    d=success_tracker.get(today)
    if not d: return None
    total=len(d)
    hit=sum(1 for x in d.values() if x.get("hit"))
    fail=total-hit
    result = {
        "date": str(today),
        "total": total,
        "hit": hit,
        "fail": fail,
        "success_rate": round((hit/total)*100,2) if total else 0
    }

    if include_details:
        success_signals = []
        for sym, meta in d.items():
            if meta.get("hit"):
                success_signals.append({
                    "symbol": sym,
                    "algorithm": meta.get("algorithm","-"),
                    "time": meta.get("time","-"),
                    "price": fmt(meta.get("entry"))
                })
        result["success_signals"] = success_signals
    return result

def format_signal_message(symbol, signals):
    if not signals: return None
    s0 = signals[0]
    lines=[
        f"📈 {symbol}",
        f"💰 Fiyat: {s0.get('current_price','-')}",
        f"📊 RSI: {s0.get('rsi','-')}",
        f"📐 EMA20 / EMA50 / EMA200: {s0.get('ema20','-')} / {s0.get('ema50','-')} / {s0.get('ema200','-')}",
        f"📉 EMA Trend: {s0.get('ema_trend','-')}",
        f"⏱ Saat: {s0.get('time','-')}", ""
    ]
    for s in s0.get("combined_algorithms", []):
        lines.append(f"{s.get('emoji','⚡')} {s['type']} | Güç: %{s['strength']} | {s.get('action','')}")
        if s.get("support"): lines.append(f"🟢 Destek: {s['support']}")
        if s.get("resistance"): lines.append(f"🔴 Direnç: {s['resistance']}")
    return "\n".join(lines)
