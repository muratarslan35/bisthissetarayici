from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils import (
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history
)

REPEAT_BLOCK_MINUTES = 45
TARGET_PCT = 0.015

LAST_SENT = {}
SUCCESS_TRACKER = {}
LAST_SIGNAL_STATE = {}

TR_TZ = ZoneInfo("Europe/Istanbul")

# ======================================================
# HELPER LEVELS
# ======================================================

HELPER_LEVELS = {
    "ORDER BLOCK": "A",
    "1H YAPISAL KIRILIM": "A",
    "4H TREND KIRILIMI": "A",

    "ÇOKLU ZAMAN EMA ONAYI": "B",
    "GOLDEN CROSS": "B",
    "L3 GÜÇLÜ KIRILIM": "B",

    "RSI DÜŞÜK": "C",
    "RSI AŞIRI SATIM": "C",
    "3LÜ TEPE": "C",
    "L2 KIRILIM": "C",
}

HELPER_DESCRIPTIONS = {
    "ORDER BLOCK": "Kurumsal alım bölgesi",
    "1H YAPISAL KIRILIM": "Saatlik yapıda kalıcı direnç aşımı",
    "4H TREND KIRILIMI": "4 saatlik ana trend yukarı kırıldı",

    "ÇOKLU ZAMAN EMA ONAYI": "15m–1H–4H EMA hizalanması",
    "GOLDEN CROSS": "Uzun vadeli trend dönüşü",
    "L3 GÜÇLÜ KIRILIM": "Orta seviye yapısal kırılım",

    "RSI DÜŞÜK": "Momentum başlangıç aşaması",
    "RSI AŞIRI SATIM": "Aşırı satımdan dönüş",
    "3LÜ TEPE": "Zayıf yapı – izleme",
    "L2 KIRILIM": "Zayıf kırılım",
}

# ======================================================
# TIME
# ======================================================

def tr_now():
    return datetime.now(TR_TZ)

def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

# ======================================================
# REPEAT BLOCK
# ======================================================

def in_repeat_block(symbol, algo):
    t = LAST_SENT.get((symbol, algo))
    return t and tr_now() < t

def mark_sent(symbol, algo):
    LAST_SENT[(symbol, algo)] = tr_now() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

# ======================================================
# TREND
# ======================================================

def ema_trend(e20, e50, e200):
    if e20 > e50 > e200:
        return "📈 YUKARI"
    if e20 < e50 < e200:
        return "📉 AŞAĞI"
    return "➖ YATAY"

# ======================================================
# HELPERS
# ======================================================

def detect_order_block(df):
    if df is None or len(df) < 20:
        return False
    last = df.iloc[-1]
    reds = df.iloc[-8:-1]
    reds = reds[reds["Close"] < reds["Open"]]
    if reds.empty:
        return False
    ob = reds.iloc[-1]
    return last["Close"] > ob["High"]

def detect_l2_l3_l4(df, price):
    helpers = []
    levels = nearest_support_resistance_from_history(df)
    for lvl in levels:
        if price <= lvl["level"]:
            continue
        s = lvl.get("strength", 0)
        if s == 4:
            helpers.append(("L4 MAJÖR KIRILIM", 20))
        elif s == 3:
            helpers.append(("L3 GÜÇLÜ KIRILIM", 12))
        elif s == 2:
            helpers.append(("L2 KIRILIM", 6))
    return helpers

def helper_indicators(item):
    helpers = []

    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    tf1d = item["tf"].get("1d")

    rsi = tf15.get("rsi")
    if rsi is not None:
        if rsi < 28:
            helpers.append(("RSI AŞIRI SATIM", 12))
        elif rsi < 35:
            helpers.append(("RSI DÜŞÜK", 6))

    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 10))

    df15 = tf15.get("df")
    if df15 is not None:
        if detect_three_peaks(df15["Close"]):
            helpers.append(("3LÜ TEPE", 8))
        if detect_order_block(df15):
            helpers.append(("ORDER BLOCK", 15))
        helpers.extend(detect_l2_l3_l4(df15, item["current_price"]))

    if tf1h and detect_support_resistance_break(tf1h["df"]):
        helpers.append(("1H YAPISAL KIRILIM", 20))

    if tf4h and detect_support_resistance_break(tf4h["df"]):
        helpers.append(("4H TREND KIRILIMI", 25))

    if tf1h and tf4h:
        if (
            tf15["ema20"] > tf15["ema50"] and
            tf1h["ema20"] > tf1h["ema50"] and
            tf4h["ema20"] > tf4h["ema50"]
        ):
            helpers.append(("ÇOKLU ZAMAN EMA ONAYI", 10))

    if tf1d and tf1d.get("ema50") > tf1d.get("ema200"):
        helpers.append(("GOLDEN CROSS", 10))

    return helpers

# ======================================================
# MAIN ALGORITHMS
# ======================================================

def is_green(df, idx):
    return df.iloc[idx]["Close"] > df.iloc[idx]["Open"]

def kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1d = item["tf"].get("1d")
    tf4h = item["tf"].get("4h")
    tf1h = item["tf"].get("1h")

    if not tf1d or not tf4h or not tf1h:
        return None

    dfd = tf1d["df"]
    df4 = tf4h["df"]
    df1 = tf1h["df"]

    if len(dfd) < 2 or len(df4) < 3 or len(df1) < 1:
        return None

    # 1D: son tamamlanmış mum yeşil
    if not is_green(dfd, -2):
        return None

    # 4H: kırmızı → yeşil dönüş (ilk yeşil mum)
    if not (
        df4.iloc[-3]["Close"] < df4.iloc[-3]["Open"] and
        df4.iloc[-2]["Close"] > df4.iloc[-2]["Open"]
    ):
        return None

    # 1H: aktif mum yeşil
    if not is_green(df1, -1):
        return None

    if tf1d["rsi"] >= 50 or tf4h["rsi"] >= 50:
        return None

    e20, e50, e200 = (
        tf15.get("ema20_live"),
        tf15.get("ema50_live"),
        tf15.get("ema200_live"),
    )
    if not (e20 and e50 and e200 and e20 > e50 > e200):
        return None

    return {"main_type": "KOMBİNE", "base_strength": 55}

def super_kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1d = item["tf"].get("1d")
    tf4h = item["tf"].get("4h")
    tf1h = item["tf"].get("1h")

    if not tf1d or not tf4h or not tf1h:
        return None

    dfd = tf1d["df"]
    df4 = tf4h["df"]
    df1 = tf1h["df"]

    if len(dfd) < 4 or len(df4) < 2 or len(df1) < 2:
        return None

    if not (is_green(dfd, -2) and is_green(dfd, -1)):
        return None
    if not (is_green(df4, -2) or is_green(df4, -1)):
        return None
    if not is_green(df1, -1):
        return None

    if tf1d["rsi"] >= 48 or tf4h["rsi"] >= 48:
        return None

    e20, e50, e200 = tf15.get("ema20_live"), tf15.get("ema50_live"), tf15.get("ema200_live")
    if not (e20 and e50 and e200 and e20 > e50 > e200):
        return None

    return {"main_type": "SÜPER KOMBİNE", "base_strength": 75}

# ======================================================
# PROCESS
# ======================================================

def process_symbol_signals(item):
    symbol = item["symbol"]
    price = item["current_price"]

    main = super_kombine_signal(item) or kombine_signal(item)
    if not main:
        return []

    algo = main["main_type"]
    helpers = helper_indicators(item)
    helper_names = set(h[0] for h in helpers)

    levels = {"A": 0, "B": 0, "C": 0}
    for h in helper_names:
        lvl = HELPER_LEVELS.get(h)
        if lvl:
            levels[lvl] += 1

    if levels["A"] >= 1:
        action, category, title = "GÜÇLÜ AL", "strong", "🚀 GÜÇLÜ AL – A Seviye Onay"
    elif levels["B"] >= 1:
        action, category, title = "AL", "combo", "📈 AL – B Seviye Onay"
    elif levels["C"] >= 1:
        action, category, title = "İZLE", "watch", "👀 İZLE – Erken Yapı"
    else:
        return []

    prev = LAST_SIGNAL_STATE.get(symbol)
    strengthened = prev and action != prev["action"]

    if in_repeat_block(symbol, algo) and not strengthened:
        return []

    mark_sent(symbol, algo)

    now_h = tr_now().strftime("%H:%M")
    history = prev["history"][:] if prev else [(now_h, f"{algo} sinyal")]
    if strengthened:
        history.append((now_h, f"{prev['action']} → {action}"))

    LAST_SIGNAL_STATE[symbol] = {"action": action, "history": history}

    df15 = item["tf"]["15m"]["df"]
    sr = nearest_support_resistance_from_history(df15)
    r1h = next((x["level"] for x in sr if x["tf"] == "1h"), None)
    r4h = next((x["level"] for x in sr if x["tf"] == "4h"), None)

    signal = {
        "symbol": symbol,
        "title": title,
        "price": fmt(price),
        "action": action,
        "category": category,
        "main_algorithm": algo,
        "ema_trend": ema_trend(
            item["tf"]["15m"]["ema20_live"],
            item["tf"]["15m"]["ema50_live"],
            item["tf"]["15m"]["ema200_live"]
        ),
        "volume_ok": bool(item["tf"]["15m"].get("volume_ok")),
        "helpers": list(helper_names),
        "helpers_detail": [
            {"name": h, "level": HELPER_LEVELS[h], "desc": HELPER_DESCRIPTIONS.get(h, "")}
            for h in helper_names if h in HELPER_LEVELS
        ],
        "history": history,
        "time": tr_now().strftime("%H:%M:%S"),
        "resistance_1h": fmt(r1h),
        "resistance_4h": fmt(r4h),
        "tf": item["tf"]
    }

    register_success_candidate(signal)
    return [signal]

# ======================================================
# SUCCESS
# ======================================================

def register_success_candidate(signal):
    today = tr_now().date()
    SUCCESS_TRACKER.setdefault(today, {})
    SUCCESS_TRACKER[today][(signal["symbol"], signal["main_algorithm"])] = {
        "entry": signal["price"],
        "target": signal["price"] * (1 + TARGET_PCT),
        "hit": False
    }

def update_success_targets(symbol, price):
    today = tr_now().date()
    hits = []
    for (sym, algo), d in SUCCESS_TRACKER.get(today, {}).items():
        if sym == symbol and not d["hit"] and price >= d["target"]:
            d["hit"] = True
            hits.append({"symbol": sym, "algorithm": algo})
    return hits

# ======================================================
# FORMAT (TELEGRAM)
# ======================================================

def format_signal_message(signal):
    lines = [
        f"📊 {signal['symbol']}",
        f"🏷 {signal['title']}",
        f"💰 Canlı Fiyat: {signal['price']}",
        f"⚡ Sinyal: {signal['action']}",
        f"🧠 Algo: {signal['main_algorithm']}",
        f"📈 Trend: {signal['ema_trend']}",
        f"📊 Hacim: {'YÜKSEK' if signal.get('volume_ok') else 'Normal'}",
    ]

    if signal.get("helpers_detail"):
        lines.append("\n🧩 Yardımcılar:")
        for h in signal["helpers_detail"]:
            lines.append(f"• [{h['level']}] {h['name']} – {h['desc']}")

    if signal.get("resistance_1h") or signal.get("resistance_4h"):
        lines.append("\n📍 Dirençler:")
        if signal.get("resistance_1h"):
            lines.append(f"• 1H: {signal['resistance_1h']}")
        if signal.get("resistance_4h"):
            lines.append(f"• 4H: {signal['resistance_4h']}")

    if signal.get("history"):
        lines.append("\n🕒 Gelişim:")
        for t, msg in signal["history"][-4:]:
            lines.append(f"{t} → {msg}")

    lines.append(f"\n⏰ {signal['time']}")
    return "\n".join(lines)

# ======================================================
# BULK
# ======================================================

def process_signals(data):
    out = []
    for item in data:
        try:
            out.extend(process_symbol_signals(item))
        except Exception:
            continue
    return out
