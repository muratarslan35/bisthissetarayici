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

def trend_consistency_15m_1h_4h(tf_15m, tf_1h, tf_4h):
    def trend(ema20, ema50, ema200):
        if ema20 and ema50 and ema200:
            if ema20 > ema50 > ema200: return "UP"
            if ema20 < ema50 < ema200: return "DOWN"
        return "NEUTRAL"

    t15 = trend(tf_15m.get("ema20"), tf_15m.get("ema50"), tf_15m.get("ema200"))
    t1h = trend(tf_1h.get("ema20"), tf_1h.get("ema50"), tf_1h.get("ema200"))
    t4h = trend(tf_4h.get("ema20"), tf_4h.get("ema50"), tf_4h.get("ema200"))

    if t15 == "UP":
        return t1h == "UP" and t4h == "UP"
    if t15 == "DOWN":
        return t1h == "DOWN" and t4h == "DOWN"
    return False

def combined_signal(item):
    tf15 = item["tf"].get("15m")
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    if not tf15 or not tf1h or not tf4h: return None
    if not trend_consistency_15m_1h_4h(tf15, tf1h, tf4h): return None
    if tf15.get("rsi") and tf15["rsi"] < 30 and not in_repeat_block(item["symbol"], "kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "kombine")
        return enrich_meta(item, tf15, {"type":"kombine","emoji":"🧠","strength":70})

def super_combined_signal(item):
    tf15 = item["tf"].get("15m")
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    if not tf15 or not tf1h or not tf4h: return None
    if not trend_consistency_15m_1h_4h(tf15, tf1h, tf4h): return None
    if tf15.get("rsi") and tf15["rsi"] < 25 and not in_repeat_block(item["symbol"], "super_kombine"):
        register_signal(item["symbol"], item["current_price"])
        mark_sent(item["symbol"], "super_kombine")
        return enrich_meta(item, tf15, {"type":"super_kombine","emoji":"🚀","strength":90})

def pullback_signal(item):
    tf15 = item["tf"].get("15m")
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    if not tf15 or not tf1h or not tf4h: return None
    if not trend_consistency_15m_1h_4h(tf15, tf1h, tf4h): return None
    if tf15.get("rsi") and tf15.get("ema20") and tf15.get("ema50"):
        if tf15["rsi"] < 40 and tf15["ema20"] > tf15["ema50"] and not in_repeat_block(item["symbol"], "pullback"):
            mark_sent(item["symbol"], "pullback")
            return enrich_meta(item, tf15, {"type":"pullback","emoji":"🔄","strength":60})

def strong_pullback_signal(item):
    tf15 = item["tf"].get("15m")
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    if not tf15 or not tf1h or not tf4h: return None
    if not trend_consistency_15m_1h_4h(tf15, tf1h, tf4h): return None
    if tf15.get("rsi") and tf15["rsi"] < 25 and not in_repeat_block(item["symbol"], "strong_pullback"):
        mark_sent(item["symbol"], "strong_pullback")
        return enrich_meta(item, tf15, {"type":"GÜÇLÜ PULLBACK","emoji":"💪","strength":85})

def three_peak_signal(item):
    tf15 = item["tf"].get("15m")
    if not tf15 or not tf15.get("df"): return None
    if detect_three_peaks(tf15["df"]["Close"]) and not in_repeat_block(item["symbol"], "three_peak"):
        mark_sent(item["symbol"], "three_peak")
        return enrich_meta(item, tf15, {"type":"three_peak","emoji":"📉➡️📈","strength":80})

def support_resistance_break_signal(item):
    tf15 = item["tf"].get("15m")
    if not tf15 or not tf15.get("df"): return None
    _, r_break = detect_support_resistance_break(tf15["df"])
    sup, res = nearest_support_resistance_from_history(tf15["df"])
    if r_break and not in_repeat_block(item["symbol"], "resistance_break"):
        mark_sent(item["symbol"], "resistance_break")
        return enrich_meta(item, tf15, {"type":"resistance_break","emoji":"🚧","strength":75,"support":fmt(sup),"resistance":fmt(res)})

def process_signals(item, market_open=True):
    signals=[]
    for fn in [
        combined_signal, super_combined_signal, pullback_signal,
        strong_pullback_signal, three_peak_signal, support_resistance_break_signal
    ]:
        r=fn(item)
        if r: signals.append(r)

    if signals:
        c=signals[0].copy()
        c["combined_algorithms"]=[{
            "type":s["type"],
            "emoji":s["emoji"],
            "strength":s["strength"],
            "action":s["action"],
            "support":s.get("support"),
            "resistance":s.get("resistance"),
            "time":s["time"]
        } for s in signals]
        return [c]
    return []

def safe_process_bist_data(data_list, market_open=True):
    res=[]
    for item in data_list:
        try:
            r=process_signals(item, market_open)
            if r: res.extend(r)
            update_success(item["symbol"], item["current_price"])
        except Exception:
            continue
    return res

def scan_strong_stocks(data):
    out=[]
    for i in data:
        tf=i.get("tf",{}).get("1d",{})
        if tf and tf.get("ema50") and tf.get("ema200") and tf["ema50"]>tf["ema200"]:
            out.append(f"• {i['symbol']}")
    return out[:10]

def daily_success_summary(include_details=False, max_failures=0):
    today=now_tr().date()
    d=success_tracker.get(today)
    if not d: return None
    total=len(d)
    hit=sum(1 for x in d.values() if x.get("hit"))
    result={
        "date":str(today),
        "total":total,
        "hit":hit,
        "fail":total-hit,
        "success_rate":round((hit/total)*100,2) if total else 0
    }
    if include_details:
        result["success_signals"]=[{
            "symbol":s,
            "algorithm":m.get("algorithm"),
            "time":m.get("time"),
            "price":fmt(m.get("entry"))
        } for s,m in d.items() if m.get("hit")]
    return result

def format_signal_message(symbol, signals):
    if not signals: return None
    s=signals[0]
    lines=[
        f"📈 {symbol}",
        f"💰 Fiyat: {s.get('current_price')}",
        f"📊 RSI: {s.get('rsi')}",
        f"📐 EMA20 / EMA50 / EMA200: {s.get('ema20')} / {s.get('ema50')} / {s.get('ema200')}",
        f"📉 EMA Trend: {s.get('ema_trend')}",
        f"⏱ Saat: {s.get('time')}",
        ""
    ]
    for a in s.get("combined_algorithms",[]):
        lines.append(f"{a['emoji']} {a['type']} | Güç: %{a['strength']} | {a['action']}")
    return "\n".join(lines)
