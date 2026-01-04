from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from utils import (
    detect_three_peaks,
    detect_support_resistance_break, 
    get_last_resistance
)

# ======================================================
# GLOBALS
# ======================================================

REPEAT_BLOCK_MINUTES = 45
TARGET_PCT = 0.015

POWER_STRENGTH_THRESHOLD = 20

LAST_SENT = {}
LAST_SIGNAL_STATE = {}
SUCCESS_TRACKER = {}

TR_TZ = ZoneInfo("Europe/Istanbul")

# ======================================================
# HELPER LEVELS
# ======================================================

HELPER_LEVELS = {
    "ORDER BLOCK": "A",
    "1H YAPISAL KIRILIM": "A",
    "4H TREND KIRILIMI": "A",
    "4H SIKIŞMA KIRILIMI (ONAYLI)": "A",
    "MOST 4H YUKARI": "A",

    "ÇOKLU ZAMAN EMA ONAYI": "B",
    "GOLDEN CROSS": "B",
    "L3 GÜÇLÜ KIRILIM": "B",
    "MOST 1D YUKARI": "B",

    "RSI DÜŞÜK": "C",
    "RSI AŞIRI SATIM": "C",
    "3LÜ TEPE": "C",
    "L2 KIRILIM": "C",
    "MOST KIRILIMI": "C",
}

HELPER_DESCRIPTIONS = {
    "ORDER BLOCK": "Kurumsal alım bölgesi",
    "1H YAPISAL KIRILIM": "Saatlik yapıda kalıcı direnç aşımı",
    "4H TREND KIRILIMI": "4 saatlik ana trend yukarı kırıldı",
    "4H SIKIŞMA KIRILIMI (ONAYLI)": "4H dar bant sıkışması sonrası hacimli ve onaylı kırılım",
    "MOST 4H YUKARI": "4 saatlik MOST trendi yukarı – trend taşınabilir",

    "ÇOKLU ZAMAN EMA ONAYI": "15m–1H–4H EMA hizalanması",
    "GOLDEN CROSS": "Uzun vadeli trend dönüşü",
    "L3 GÜÇLÜ KIRILIM": "Orta seviye yapısal kırılım",
    "MOST 1D YUKARI": "Günlük MOST trendi yukarı – büyük resim onayı",

    "RSI DÜŞÜK": "Momentum başlangıç aşaması",
    "RSI AŞIRI SATIM": "Aşırı satımdan dönüş",
    "3LÜ TEPE": "Zayıf yapı – izleme",
    "L2 KIRILIM": "Zayıf kırılım",
    "MOST KIRILIMI": "MOST trendi aşağı kırıldı – risk arttı",
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
# CANDLE HELPERS
# ======================================================

def is_green(df, idx):
    return df.iloc[idx]["Close"] > df.iloc[idx]["Open"]

def is_4h_first_green_after_red(df):
    if df is None or len(df) < 3:
        return False
    return (
        df.iloc[-3]["Close"] < df.iloc[-3]["Open"] and
        df.iloc[-2]["Close"] > df.iloc[-2]["Open"]
    )

def is_4h_trend_green(df):
    if df is None or len(df) < 2:
        return False
    return (
        df.iloc[-2]["Close"] > df.iloc[-2]["Open"] or
        df.iloc[-1]["Close"] > df.iloc[-1]["Open"]
    )

# ======================================================
# 4H SIKIŞMA + ONAYLI KIRILIM
# ======================================================

def detect_4h_squeeze_breakout(df):
    if df is None or len(df) < 10:
        return False

    zone = df.iloc[-10:-2]
    high_range = zone["High"].max()
    low_range = zone["Low"].min()

    # Dar bant (%6’dan küçük)
    if (high_range - low_range) / low_range > 0.06:
        return False

    breakout = df.iloc[-2]
    prev = df.iloc[-3]

    if breakout["Close"] <= prev["High"]:
        return False

    vol_ma = df["Volume"].rolling(10).mean().iloc[-2]
    if breakout["Volume"] <= vol_ma:
        return False

    return True

# ======================================================
# MOST (MOVING STOP) HESAPLAMA
# ======================================================

def calculate_most(df, period=9, multiplier=2.0):
    if df is None or len(df) < period + 2:
        return None

    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr = np.maximum(
        high - low,
        np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1)))
    )
    atr = tr.rolling(period).mean()

    most = [close.iloc[0]]
    trend = "UP"

    for i in range(1, len(close)):
        if trend == "UP":
            level = close.iloc[i] - atr.iloc[i] * multiplier
            level = max(level, most[-1])
            if close.iloc[i] < level:
                trend = "DOWN"
                level = close.iloc[i] + atr.iloc[i] * multiplier
        else:
            level = close.iloc[i] + atr.iloc[i] * multiplier
            level = min(level, most[-1])
            if close.iloc[i] > level:
                trend = "UP"
                level = close.iloc[i] - atr.iloc[i] * multiplier

        most.append(level)

    return {
        "trend": trend,
        "level": most[-1],
        "prev_level": most[-2]
    }

def detect_most_trend(df):
    res = calculate_most(df)
    if not res:
        return None

    if res["trend"] == "UP":
        return "UP"
    return "DOWN"

# ======================================================
# HELPERS
# ======================================================

def detect_order_block(df):
    if df is None or len(df) < 20:
        return False

    reds = df.iloc[-8:-1]
    reds = reds[reds["Close"] < reds["Open"]]
    if reds.empty:
        return False

    return df.iloc[-1]["Close"] > reds.iloc[-1]["High"]

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

    # =========================
    # RSI (15m)
    # =========================
    rsi = tf15.get("rsi")
    if rsi is not None:
        if rsi < 28:
            helpers.append(("RSI AŞIRI SATIM", 12))
        elif rsi < 35:
            helpers.append(("RSI DÜŞÜK", 6))

    # =========================
    # HACİM
    # =========================
    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 10))

    # =========================
    # ORDER BLOCK / L2-L3-L4
    # =========================
    df15 = tf15.get("df")
    if df15 is not None:
        if detect_three_peaks(df15["Close"]):
            helpers.append(("3LÜ TEPE", 8))

        if detect_order_block(df15):
            helpers.append(("ORDER BLOCK", 15))

        helpers.extend(
            detect_l2_l3_l4(df15, item["current_price"])
        )

    # =========================
    # 1H YAPISAL KIRILIM
    # =========================
    if tf1h and detect_support_resistance_break(tf1h["df"]):
        helpers.append(("1H YAPISAL KIRILIM", 20))

    # =========================
    # 4H TREND + SIKIŞMA
    # =========================
    if tf4h:
        if detect_support_resistance_break(tf4h["df"]):
            helpers.append(("4H TREND KIRILIMI", 25))

        if detect_4h_squeeze_breakout(tf4h["df"]):
            helpers.append(("4H SIKIŞMA KIRILIMI (ONAYLI)", 30))

    # =========================
    # EMA HİZALANMASI
    # =========================
    if tf1h and tf4h:
        if (
            tf15["ema20"] > tf15["ema50"] and
            tf1h["ema20"] > tf1h["ema50"] and
            tf4h["ema20"] > tf4h["ema50"]
        ):
            helpers.append(("ÇOKLU ZAMAN EMA ONAYI", 10))

    # =========================
    # GOLDEN CROSS (1D)
    # =========================
    if tf1d and tf1d.get("ema50") > tf1d.get("ema200"):
        helpers.append(("GOLDEN CROSS", 10))

    # =========================
    # MOST 4H + 1D (ANA TREND)
    # =========================
    if tf4h:
        most_4h = detect_most_trend(tf4h["df"])
        if most_4h == "UP":
            helpers.append(("MOST 4H YUKARI", 18))
        elif most_4h == "DOWN":
            helpers.append(("MOST 4H AŞAĞI", -20))

    if tf1d:
        most_1d = detect_most_trend(tf1d["df"])
        if most_1d == "UP":
            helpers.append(("MOST 1D YUKARI", 22))
        elif most_1d == "DOWN":
            helpers.append(("MOST 1D AŞAĞI", -30))

    return helpers

# ======================================================
# MAIN ALGORITHMS
# ======================================================

def kombine_signal(item):
    tf15 = item["tf"]["15m"]
    tf1d = item["tf"].get("1d")
    tf4h = item["tf"].get("4h")
    tf1h = item["tf"].get("1h")

    if not tf1d or not tf4h or not tf1h:
        return None

    # 1D: son TAMAMLANMIŞ mum yeşil
    if not is_green(tf1d["df"], -2):
        return None

    # 4H: kırmızı → ilk yeşil dönüş
    if not is_4h_first_green_after_red(tf4h["df"]):
        return None

    # 1H: aktif mum yeşil
    if not is_green(tf1h["df"], -1):
        return None

    # RSI filtre
    if tf1d["rsi"] >= 50:
        return None

    # 15m LIVE EMA
    e20 = tf15.get("ema20_live")
    e50 = tf15.get("ema50_live")
    e200 = tf15.get("ema200_live")

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

    # 1D: ardışık 2 yeşil
    if not (is_green(tf1d["df"], -2) and is_green(tf1d["df"], -1)):
        return None

    # 4H: trend yeşil
    if not is_4h_trend_green(tf4h["df"]):
        return None

    # 1H: aktif yeşil
    if not is_green(tf1h["df"], -1):
        return None

    # RSI daha sıkı
    if tf1d["rsi"] >= 48:
        return None

    e20 = tf15.get("ema20_live")
    e50 = tf15.get("ema50_live")
    e200 = tf15.get("ema200_live")

    if not (e20 and e50 and e200 and e20 > e50 > e200):
        return None

    return {"main_type": "SÜPER KOMBİNE", "base_strength": 75}

# ======================================================
# PROCESS SYMBOL
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

    total_power = sum(p for _, p in helpers if isinstance(p, (int, float)))

    key = (symbol, algo)
    prev = LAST_SIGNAL_STATE.get(key) or {}
    prev_power = prev.get("power", 0)
    power_delta = total_power - prev_power

    # ================= MOST STATE =================
    most_state = None
    tf4h = item["tf"].get("4h")
    if tf4h:
        most_state = detect_most_trend(tf4h["df"])

    prev_most = prev.get("most_state")

    # ================= LEVEL COUNT =================
    levels = {"A": 0, "B": 0, "C": 0}
    for h in helper_names:
        lvl = HELPER_LEVELS.get(h)
        if lvl:
            levels[lvl] += 1

    # ================= BASE ACTION =================
    if levels["A"] >= 1:
        action, category, title = "GÜÇLÜ AL", "strong", "🚀 GÜÇLÜ AL – A Seviye Onay"
    elif levels["B"] >= 1:
        action, category, title = "AL", "combo", "📈 AL – B Seviye Onay"
    elif levels["C"] >= 1:
        action, category, title = "İZLE", "watch", "👀 İZLE – Erken Yapı"
    else:
        return []

    # ================= MOST DOWN / UP =================
    most_downgrade = prev_most == "UP" and most_state == "DOWN"
    most_upgrade   = prev_most == "DOWN" and most_state == "UP"

    # 🔴 MOST KIRILIMI → HELPER EKLE
    if most_downgrade:
        helpers.append(("MOST KIRILIMI", -50))
        helper_names.add("MOST KIRILIMI")

    if most_downgrade:
        if action == "GÜÇLÜ AL":
            action, category = "AL", "combo"
            title = "⚠️ MOST AŞAĞI – GÜÇ DÜŞÜRÜLDÜ"
        elif action == "AL":
            action, category = "İZLE", "watch"
            title = "⛔ MOST AŞAĞI – İZLEME MODU"

    if most_upgrade:
        if action == "İZLE":
            action, category = "AL", "combo"
            title = "✅ MOST YUKARI – TEKRAR AL"
        elif action == "AL":
            action, category = "GÜÇLÜ AL", "strong"
            title = "🚀 MOST YUKARI – GÜÇLÜ AL"

    # ================= POWER BASED =================
    strengthened = False
    weakened = False

    if prev:
        if action != prev.get("action"):
            strengthened = True
        elif power_delta >= POWER_STRENGTH_THRESHOLD:
            strengthened = True
            title = "🔥 GÜÇLENEN SİNYAL"
        elif power_delta <= -POWER_STRENGTH_THRESHOLD:
            weakened = True
            title = "⚠️ ZAYIFLAYAN SİNYAL"
            category = "watch"

    # ================= REPEAT BLOCK =================
    if in_repeat_block(symbol, algo) and not (
        strengthened or weakened or most_upgrade or most_downgrade
    ):
        return []

    mark_sent(symbol, algo)

    # ================= HISTORY =================
    now_h = tr_now().strftime("%H:%M")
    history = prev.get("history", [(now_h, f"{algo} sinyal")])

    if most_downgrade:
        history.append((now_h, "MOST aşağı – downgrade"))
    if most_upgrade:
        history.append((now_h, "MOST yukarı – upgrade"))
    if strengthened:
        history.append((now_h, f"Güç arttı (+{power_delta})"))
    if weakened:
        history.append((now_h, f"Güç düştü ({power_delta})"))

    LAST_SIGNAL_STATE[key] = {
        "action": action,
        "history": history,
        "power": total_power,
        "most_state": most_state
    }

# ================= RESISTANCE =================
    
tf1h = item["tf"].get("1h")
tf4h = item["tf"].get("4h")

r1h = get_last_resistance(tf1h["df"]) if tf1h else None
r4h = get_last_resistance(tf4h["df"]) if tf4h else None
    
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
            {
                "name": h,
                "level": HELPER_LEVELS[h],
                "desc": HELPER_DESCRIPTIONS.get(h, "")
            }
            for h in helper_names if h in HELPER_LEVELS
        ],
        "history": history,
        "time": tr_now().strftime("%H:%M:%S"),
        "resistance_1h": fmt(r1h),
        "resistance_4h": fmt(r4h),
        "power": total_power,
        "power_delta": power_delta,
        "tf": item["tf"],
        "most_state": most_state
    }

    register_success_candidate(signal)
    return [signal]
# ======================================================
# SUCCESS TRACK
# ======================================================

def register_success_candidate(signal):
    today = tr_now().date()
    SUCCESS_TRACKER.setdefault(today, {})

    SUCCESS_TRACKER[today][
        (signal["symbol"], signal["main_algorithm"])
    ] = {
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
            hits.append({
                "symbol": sym,
                "algorithm": algo
            })

    return hits

# ======================================================
# TELEGRAM FORMAT
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
            lines.append(
                f"• [{h['level']}] {h['name']} – {h['desc']}"
            )

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
