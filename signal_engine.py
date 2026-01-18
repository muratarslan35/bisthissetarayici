from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import json
import os

from utils import (
    detect_three_peaks,
    detect_support_resistance_break,
    get_last_resistance
)
from threading import Lock
_STORE_LOCK = Lock()

# ======================================================
# PERSIST CONFIG (HAFTALIK + CUMA)
# ======================================================

DATA_DIR = "data"

DAILY_STATE_FILE = os.path.join(DATA_DIR, "daily_state.json")
WEEKLY_STATE_FILE = os.path.join(DATA_DIR, "weekly_state.json")

def load_weekly_state():
    if not os.path.exists(WEEKLY_STATE_FILE):
        return {}, {}

    try:
        with open(WEEKLY_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return (
                data.get("weekly", {}),
                data.get("friday_prices", {})
            )
    except Exception:
        return {}, {}

def save_weekly_state():
    os.makedirs(DATA_DIR, exist_ok=True)

    with _STORE_LOCK:
        with open(WEEKLY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "weekly": WEEKLY_SUCCESS_TRACKER,
                    "friday_prices": FRIDAY_CLOSE_PRICES,
                },
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )
def load_daily_state():
    if not os.path.exists(DAILY_STATE_FILE):
        return {}

    try:
        with open(DAILY_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_daily_state():
    os.makedirs(DATA_DIR, exist_ok=True)

    with _STORE_LOCK:
        with open(DAILY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                DAILY_SUCCESS_TRACKER,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )
# ======================================================
# GLOBALS
# ======================================================

REPEAT_BLOCK_MINUTES = 45
TARGET_PCT = 0.015
POWER_STRENGTH_THRESHOLD = 20

LAST_SENT = {}
LAST_SIGNAL_STATE = {}

# 🔹 GÜNLÜK (RAM – ORİJİNAL DAVRANIŞ)
DAILY_SUCCESS_TRACKER = {}
# 🔹 GÜNLÜK KAPANIŞ SNAPSHOT
DAILY_CLOSE_PRICES = {}
# 🔹 HAFTALIK + CUMA (DISK – KALICI)
WEEKLY_SUCCESS_TRACKER, FRIDAY_CLOSE_PRICES = load_weekly_state()
# 🔹 GÜNLÜK (DISK + RAM)
DAILY_SUCCESS_TRACKER = load_daily_state()

TR_TZ = ZoneInfo("Europe/Istanbul")

# ======================================================
# ZAMAN
# ======================================================

def tr_now():
    return datetime.now(TR_TZ)

def today_key():
    return tr_now().date().isoformat()

def week_key():
    now = tr_now()
    monday = now - timedelta(days=now.weekday())
    return monday.date().isoformat()

def fmt(v):
    return round(v, 2) if isinstance(v, (int, float)) else None

def is_market_close_final_window():
    now = tr_now()
    return now.hour == 18 and now.minute >= 10
# ======================================================
# RESET MEKANİZMALARI
# ======================================================

def reset_daily_success_if_needed():
    """
    Her yeni günde DAILY_SUCCESS_TRACKER sıfırlanır (RAM)
    """
    key = today_key()
    if key not in DAILY_SUCCESS_TRACKER:
        DAILY_SUCCESS_TRACKER.clear()
        DAILY_SUCCESS_TRACKER[key] = {}
        save_daily_state()
def reset_weekly_success_if_needed():
    key = week_key()

    # ⛔️ EĞER DISKTE VERİ VARSA ASLA RESETLEME
    if WEEKLY_SUCCESS_TRACKER:
        return

    # ⛔️ SADECE PAZARTESİ SABAHI VE GERÇEKTEN YENİ HAFTAYSA
    WEEKLY_SUCCESS_TRACKER[key] = {}
    FRIDAY_CLOSE_PRICES.clear()
    save_weekly_state()

# ======================================================
# HELPER SEVİYELERİ
# ======================================================

HELPER_LEVELS = {
    "ORDER BLOCK": "A",
    "1H YAPISAL KIRILIM": "A",
    "4H TREND KIRILIMI": "A",
    "4H SIKIŞMA KIRILIMI (ONAYLI)": "A",
    "MOST 4H YUKARI": "A",
    "L4 MAJÖR KIRILIM": "A",

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
    "4H SIKIŞMA KIRILIMI (ONAYLI)": "4H dar bant sıkışması sonrası hacimli kırılım",
    "MOST 4H YUKARI": "4 saatlik MOST trendi yukarı",

    "ÇOKLU ZAMAN EMA ONAYI": "15m–1H–4H EMA hizalanması",
    "GOLDEN CROSS": "Uzun vadeli trend dönüşü",
    "L3 GÜÇLÜ KIRILIM": "Orta seviye yapısal kırılım",
    "MOST 1D YUKARI": "Günlük MOST ana trend",

    "RSI DÜŞÜK": "Momentum başlangıcı",
    "RSI AŞIRI SATIM": "Aşırı satımdan dönüş",
    "3LÜ TEPE": "Zayıf yapı",
    "L2 KIRILIM": "Zayıf kırılım",
    "MOST KIRILIMI": "MOST aşağı – risk",
    "L4 MAJÖR KIRILIM": "Kurumsal majör seviye kırılımı",
}

# ======================================================
# REPEAT BLOCK
# ======================================================

def in_repeat_block(symbol, algo):
    t = LAST_SENT.get((symbol, algo))
    return t and tr_now() < t

def mark_sent(symbol, algo):
    LAST_SENT[(symbol, algo)] = tr_now() + timedelta(minutes=REPEAT_BLOCK_MINUTES)

# ======================================================
# EMA TREND
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

    # Dar bant filtresi
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
# MOST (MOVING STOP)
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
    return "UP" if res["trend"] == "UP" else "DOWN"

# ======================================================
# YARDIMCI FORMASYONLAR
# ======================================================
# ======================================================
# PROFESYONEL L2 / L3 / L4 SEVİYE ANALİZİ (FINAL)
# ======================================================

def detect_levels(df, tf, tolerance=None):
    if tolerance is None:
        tolerance = 0.006 if tf == "4h" else 0.004
    """
    Profesyonel seviye tespiti:
    - Aynı fiyat bölgesine tekrar tekrar temas
    - Gürültü filtresi
    """
    levels = []
    closes = df["Close"].values
    volumes = df["Volume"].values

    for i in range(20, len(closes) - 20):
        price = closes[i]
        touches = 0

        for j in range(i - 20, i + 20):
            if abs(closes[j] - price) / price <= tolerance:
                touches += 1

        if touches >= 2:
            levels.append({
                "level": price,
                "touches": touches,
                "volume": volumes[i]
            })

    return levels


def confirm_breakout(df, level):
    """
    Gerçek kırılım şartları:
    - Kapanış seviye üstü
    - Hacim ortalama üstü
    """
    last = df.iloc[-1]
    vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

    return (
        last["Close"] > level and
        last["Volume"] >= vol_ma
    )


def classify_level(lvl, tf):
    """
    Zaman dilimine göre seviye sınıflaması
    """
    t = lvl["touches"]

    if t >= 3 and tf in ("4h", "1d"):
        return ("L4 MAJÖR KIRILIM", 18)

    if t >= 3:
        return ("L3 GÜÇLÜ KIRILIM", 12)

    if t >= 2:
        return ("L2 KIRILIM", 6)

    return None


def detect_l2_l3_l4_pro(df, price, tf):
    """
    TEK ve GERÇEK L2 / L3 / L4 kaynağı
    """
    helpers = []

    for lvl in detect_levels(df):
        if price <= lvl["level"]:
            continue

        if not confirm_breakout(df, lvl["level"]):
            continue

        res = classify_level(lvl, tf)
        if res:
            helpers.append(res)

    return helpers
    
def detect_order_block(df):
    if df is None or len(df) < 20:
        return False

    reds = df.iloc[-8:-1]
    reds = reds[reds["Close"] < reds["Open"]]
    if reds.empty:
        return False

    return df.iloc[-1]["Close"] > reds.iloc[-1]["High"]


# ======================================================
# HELPER INDICATORS (ANA TOPLAMA)
# ======================================================
def helper_indicators(item):
    helpers = []

    tf15 = item["tf"]["15m"]
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")
    tf1d = item["tf"].get("1d")

    # RSI
    rsi = tf15.get("rsi")
    if rsi is not None:
        if rsi < 28:
            helpers.append(("RSI AŞIRI SATIM", 12))
        elif rsi < 35:
            helpers.append(("RSI DÜŞÜK", 6))

    # HACİM
    if tf15.get("volume_ok"):
        helpers.append(("GÜÇLÜ HACİM", 10))

    # ORDER BLOCK + FORMASYON
    df15 = tf15.get("df")
    if df15 is not None:
        if detect_three_peaks(df15["Close"]):
            helpers.append(("3LÜ TEPE", 8))
        if detect_order_block(df15):
            helpers.append(("ORDER BLOCK", 15))

    # L2 – 15m
    helpers.extend(
        detect_l2_l3_l4_pro(
            tf15["df"],
            item["current_price"],
            tf="15m"
        )
    )

    # L3 – 1H
    if tf1h:
        helpers.extend(
            detect_l2_l3_l4_pro(
                tf1h["df"],
                item["current_price"],
                tf="1h"
            )
        )

    # L4 – 4H
    if tf4h:
        helpers.extend(
            detect_l2_l3_l4_pro(
                tf4h["df"],
                item["current_price"],
                tf="4h"
            )
        )

    # 1H YAPISAL KIRILIM
    if tf1h and detect_support_resistance_break(tf1h["df"]):
        helpers.append(("1H YAPISAL KIRILIM", 20))

    # 4H TREND + SIKIŞMA
    if tf4h:
        if detect_support_resistance_break(tf4h["df"]):
            helpers.append(("4H TREND KIRILIMI", 25))
        if detect_4h_squeeze_breakout(tf4h["df"]):
            helpers.append(("4H SIKIŞMA KIRILIMI (ONAYLI)", 30))

    # EMA ONAY
    if tf1h and tf4h:
        if (
            tf15["ema20"] > tf15["ema50"] and
            tf1h["ema20"] > tf1h["ema50"] and
            tf4h["ema20"] > tf4h["ema50"]
        ):
            helpers.append(("ÇOKLU ZAMAN EMA ONAYI", 10))

    # GOLDEN CROSS
    if tf1d and tf1d.get("ema50") > tf1d.get("ema200"):
        helpers.append(("GOLDEN CROSS", 10))

    # MOST
    if tf4h:
        m4 = detect_most_trend(tf4h["df"])
        if m4 == "UP":
            helpers.append(("MOST 4H YUKARI", 18))
        elif m4 == "DOWN":
            helpers.append(("MOST 4H AŞAĞI", -20))

    if tf1d:
        m1 = detect_most_trend(tf1d["df"])
        if m1 == "UP":
            helpers.append(("MOST 1D YUKARI", 22))
        elif m1 == "DOWN":
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

    if not is_green(tf1d["df"], -2):
        return None

    if not is_4h_first_green_after_red(tf4h["df"]):
        return None

    if not is_green(tf1h["df"], -1):
        return None

    if tf1d["rsi"] >= 50:
        return None

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

    if not (
        is_green(tf1d["df"], -2) and
        is_green(tf1d["df"], -1)
    ):
        return None

    if not is_4h_trend_green(tf4h["df"]):
        return None

    if not is_green(tf1h["df"], -1):
        return None

    if tf1d["rsi"] >= 48:
        return None

    e20 = tf15.get("ema20_live")
    e50 = tf15.get("ema50_live")
    e200 = tf15.get("ema200_live")

    if not (e20 and e50 and e200 and e20 > e50 > e200):
        return None

    return {"main_type": "SÜPER KOMBİNE", "base_strength": 75}

# ======================================================
# PROCESS SYMBOL SIGNALS
# ======================================================

def process_symbol_signals(item):
    symbol = item["symbol"]
    price = item["current_price"]

    # ✅ DOĞRU RESET FONKSİYONLARI
    reset_daily_success_if_needed()
    reset_weekly_success_if_needed()

    # --------------------------------------------------
    # ANA ALGORİTMA
    # --------------------------------------------------
    main = super_kombine_signal(item) or kombine_signal(item)
    if not main:
        return []

    algo = main["main_type"]

    # --------------------------------------------------
    # HELPERS + POWER
    # --------------------------------------------------
    helpers = helper_indicators(item)
    helper_map = {h[0]: h[1] for h in helpers}
    helper_names = set(helper_map.keys())

    total_power = sum(
        v for v in helper_map.values()
        if isinstance(v, (int, float))
    )

    key = (symbol, algo)
    prev = LAST_SIGNAL_STATE.get(key, {})

    prev_power = prev.get("power", 0)
    power_delta = total_power - prev_power

    prev_helpers = set(prev.get("helpers", []))
    added_helpers = list(helper_names - prev_helpers)
    removed_helpers = list(prev_helpers - helper_names)

    # --------------------------------------------------
    # MOST (1H + 4H)
    # --------------------------------------------------
    tf1h = item["tf"].get("1h")
    tf4h = item["tf"].get("4h")

    most_1h = detect_most_trend(tf1h["df"]) if tf1h else None
    most_4h = detect_most_trend(tf4h["df"]) if tf4h else None

    prev_most_4h = prev.get("most_4h")

    most_downgrade = prev_most_4h == "UP" and most_4h == "DOWN"
    most_upgrade = prev_most_4h == "DOWN" and most_4h == "UP"

    if most_downgrade:
        helper_names.add("MOST KIRILIMI")
        helper_map["MOST KIRILIMI"] = -50

    # --------------------------------------------------
    # SEVİYE SAYIMI
    # --------------------------------------------------
    levels = {"A": 0, "B": 0, "C": 0}
    for h in helper_names:
        lvl = HELPER_LEVELS.get(h)
        if lvl:
            levels[lvl] += 1

    # --------------------------------------------------
    # AKSİYON
    # --------------------------------------------------
    if levels["A"] >= 1:
        action, category, title = "GÜÇLÜ AL", "strong", "🚀 GÜÇLÜ AL – A Seviye"
    elif levels["B"] >= 1:
        action, category, title = "AL", "combo", "📈 AL – B Seviye"
    elif levels["C"] >= 1:
        action, category, title = "İZLE", "watch", "👀 İZLE"
    else:
        return []

    # --------------------------------------------------
    # MOST DOWNGRADE / UPGRADE
    # --------------------------------------------------
    if most_downgrade:
        if action == "GÜÇLÜ AL":
            action, category = "AL", "combo"
            title = "⚠️ MOST 4H AŞAĞI – GÜÇ DÜŞÜRÜLDÜ"
        elif action == "AL":
            action, category = "İZLE", "watch"
            title = "⛔ MOST 4H AŞAĞI – İZLE"

    if most_upgrade:
        if action == "İZLE":
            action, category = "AL", "combo"
            title = "✅ MOST 4H YUKARI – TEKRAR AL"
        elif action == "AL":
            action, category = "GÜÇLÜ AL", "strong"
            title = "🚀 MOST 4H YUKARI – GÜÇLÜ AL"

    # --------------------------------------------------
    # POWER DEĞİŞİMİ
    # --------------------------------------------------
    strengthened = False
    weakened = False

    if prev:
        if power_delta >= POWER_STRENGTH_THRESHOLD:
            strengthened = True
            title = "🔥 GÜÇLENEN SİNYAL"
        elif power_delta <= -POWER_STRENGTH_THRESHOLD:
            weakened = True
            title = "⚠️ ZAYIFLAYAN SİNYAL"
            category = "watch"

    # --------------------------------------------------
    # REPEAT BLOCK
    # --------------------------------------------------
    # 🔑 İLK SİNYAL ASLA SUSTURULMAZ
    is_first_entry = (symbol, algo) not in LAST_SIGNAL_STATE

    if not is_first_entry and in_repeat_block(symbol, algo) and not (
    strengthened or weakened or most_upgrade or most_downgrade
    ):
        return []

    mark_sent(symbol, algo)

    # --------------------------------------------------
    # HISTORY
    # --------------------------------------------------
    now_h = tr_now().strftime("%H:%M")
    history = prev.get("history", [(now_h, f"{algo} sinyal")])

    if added_helpers:
        history.append((now_h, f"Eklendi: {', '.join(added_helpers)}"))
    if removed_helpers:
        history.append((now_h, f"Çıktı: {', '.join(removed_helpers)}"))

    if most_downgrade:
        history.append((now_h, "MOST 4H aşağı – downgrade"))
    if most_upgrade:
        history.append((now_h, "MOST 4H yukarı – upgrade"))

    if strengthened:
        history.append((now_h, f"Güç arttı (+{power_delta})"))
    if weakened:
        history.append((now_h, f"Güç düştü ({power_delta})"))

    # --------------------------------------------------
    # STATE KAYDI
    # --------------------------------------------------
    LAST_SIGNAL_STATE[key] = {
        "power": total_power,
        "helpers": list(helper_names),
        "most_4h": most_4h,
        "history": history,
    }

    # --------------------------------------------------
    # DİRENÇLER
    # --------------------------------------------------
    r1h = get_last_resistance(tf1h["df"]) if tf1h else None
    r4h = get_last_resistance(tf4h["df"]) if tf4h else None

    r1h_dist_pct = round(((r1h - price) / price) * 100, 2) if r1h else None
    r4h_dist_pct = round(((r4h - price) / price) * 100, 2) if r4h else None

    # --------------------------------------------------
    # MOST SEVİYELERİ (GERÇEK)
    # --------------------------------------------------
    most_1h_level = None
    most_4h_level = None

    if tf1h:
        m1 = calculate_most(tf1h["df"])
        if m1:
            most_1h_level = round(m1["level"], 2)

    if tf4h:
        m4 = calculate_most(tf4h["df"])
        if m4:
            most_4h_level = round(m4["level"], 2)

    # --------------------------------------------------
    # ENTRY (SABİT)
    # --------------------------------------------------
    t_key = today_key()
    w_key = week_key()

    entry_price = None
    if (symbol, algo) in DAILY_SUCCESS_TRACKER.get(t_key, {}):
        entry_price = DAILY_SUCCESS_TRACKER[t_key][(symbol, algo)]["entry"]

    # --------------------------------------------------
    # TP HESAPLARI
    # --------------------------------------------------
    tp1 = round(entry_price * 1.015, 2) if entry_price else None
    tp2 = round(entry_price * 1.03, 2) if entry_price else None
    tp3 = round(entry_price * 1.05, 2) if entry_price else None

    # --------------------------------------------------
    # CANLI GETİRİ % (DASHBOARD + OKLAR)
    # --------------------------------------------------
    live_gain_pct = None
    if entry_price is not None and price is not None:
        try:
            live_gain_pct = round(
                ((price - entry_price) / entry_price) * 100, 2
            )
        except Exception:
            live_gain_pct = None

    # --------------------------------------------------
    # SIGNAL OBJESİ
    # --------------------------------------------------
    signal = {
        "symbol": symbol,
        "entry_price": fmt(entry_price),
        "price": fmt(price),
        "live_gain_pct": live_gain_pct,

        "title": title,
        "action": action,
        "category": category,
        "main_algorithm": algo,

        "ema_trend": ema_trend(
            item["tf"]["15m"]["ema20_live"],
            item["tf"]["15m"]["ema50_live"],
            item["tf"]["15m"]["ema200_live"]
        ),

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
        "resistance_1h_pct": r1h_dist_pct,
        "resistance_4h_pct": r4h_dist_pct,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "most_1h": most_1h,
        "most_4h": most_4h,
        "most_1h_level": most_1h_level,
        "most_4h_level": most_4h_level,

        "power": total_power,
        "power_delta": power_delta,
    }
    # --------------------------------------------------
    # 🔒 YAYIN KONTROLÜ (GİZLİ TARAMA FİLTRESİ)
    # --------------------------------------------------
    # Bu sinyal günlük veya haftalık kayda girmiyorsa:
    # - Dashboarda düşmez
    # - Telegrama gitmez
    # - Weekly tabloya sızmaz

    daily = False
    weekly = False

    t_key = today_key()
    w_key = week_key()

    if (symbol, algo) in DAILY_SUCCESS_TRACKER.get(t_key, {}):
        daily = True

    if (symbol, algo) in WEEKLY_SUCCESS_TRACKER.get(w_key, {}):
        weekly = True

    # ❌ HİÇBİR TRACKER'A GİRMİYORSA → YOK SAY
    if not daily and not weekly:
        return []

    # ✅ BU NOKTADAN SONRAKİ SİNYAL GERÇEKTİR
    signal["published"] = True
    
    # --------------------------------------------------
    # ENTRY KAYDI (GÜNLÜK + HAFTALIK)
    # --------------------------------------------------
    d_store = DAILY_SUCCESS_TRACKER.setdefault(t_key, {})
    w_store = WEEKLY_SUCCESS_TRACKER.setdefault(w_key, {})

    # ---- DAILY (RAM) ----
    if (symbol, algo) not in d_store:
        d_store[(symbol, algo)] = {
            "symbol": symbol,
            "algo": algo,
            "helpers": list(helper_names),
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "entry_time": tr_now().strftime("%H:%M:%S"),
            "entry_date": tr_now().date(),
        }
        save_daily_state()
    # ---- WEEKLY (DISK) ----
    if (symbol, algo) not in w_store:
        w_store[(symbol, algo)] = {
            "symbol": symbol,
            "algo": algo,
            "helpers": list(helper_names),

            # fiyatlar
            "entry": price,
            "target": price * (1 + TARGET_PCT),

            # durum
            "hit": False,
            "hit_price": None,
            "hit_time": None,
            "hit_day": None,

            # zaman (dashboard için ZORUNLU)
            "entry_day": tr_now().strftime("%A"),
            "entry_date": tr_now().date(),
            "entry_time": tr_now().strftime("%H:%M:%S"),
        }
    
        save_weekly_state()
    

    return [signal]

# ======================================================
# FRIDAY CLOSE SNAPSHOT
# ======================================================

def capture_friday_close(symbol, price):
    """
    Cuma günü 18:05–18:10 arasında son fiyatı yakalar
    """
    now = tr_now()

    if now.weekday() != 4:  # cuma değil
        return

    if now.hour == 18 and 5 <= now.minute <= 10:
        FRIDAY_CLOSE_PRICES.setdefault(symbol, price)
        save_weekly_state()
        
def capture_daily_close(symbol, price):
    if not is_market_close_final_window():
        return

    DAILY_CLOSE_PRICES.setdefault(symbol, price)
# ======================================================
# SUCCESS TARGET UPDATE (DAILY + WEEKLY)
# ======================================================

def update_success_targets(symbol, price):
    # Günlük kapanış snapshot
    capture_daily_close(symbol, price)
    # app.py scanner loop her turda çağırıyor
    reset_daily_success_if_needed()
    reset_weekly_success_if_needed()

    # ✅ Cuma kapanış fiyatını yakala
    capture_friday_close(symbol, price)

    t_key = today_key()
    w_key = week_key()

    success_signals = []

    daily = DAILY_SUCCESS_TRACKER.get(t_key, {})
    weekly = WEEKLY_SUCCESS_TRACKER.get(w_key, {})

    # ---------- DAILY ----------
    for (sym, algo), d in daily.items():
        if d.get("hit"):
            continue
        if sym != symbol:
            continue

        if price >= d["target"]:
            d["hit"] = True
            d["hit_price"] = price
            d["hit_time"] = tr_now().strftime("%H:%M:%S")
            save_daily_state()
            entry = d["entry"]

            success_signals.append({
                "symbol": sym,
                "title": "🎯 HEDEF GELDİ",
                "price": fmt(price),
                "action": "BAŞARILI",
                "category": "success",
                "main_algorithm": algo,
                "entry_price": fmt(entry),
                "target_price": fmt(d["target"]),
                "hit_price": fmt(price),
                "gain_pct": round(((price - entry) / entry) * 100, 2),
                "time": d["hit_time"],
                "helpers": d.get("helpers", []),
                "history": [
                    ("ENTRY", f"{fmt(entry)}"),
                    ("TARGET", f"{fmt(d['target'])}"),
                    ("HIT", f"{fmt(price)}"),
                ],
            })

    # ---------- WEEKLY (SADECE TAKİP, MESAJ YOK) ----------
    for (sym, algo), d in weekly.items():
        if d.get("hit"):
            continue
        if sym != symbol:
            continue

        if price >= d["target"]:
            d["hit"] = True
            d["hit_price"] = price
            d["hit_time"] = tr_now().strftime("%H:%M:%S")
            d["hit_day"] = tr_now().strftime("%A")
            save_weekly_state()
    return success_signals


# ======================================================
# DAILY SUCCESS REPORT (TELEGRAM)
# ======================================================

def build_daily_success_report():
    t_key = today_key()
    day_data = DAILY_SUCCESS_TRACKER.get(t_key, {})

    if not day_data:
        return None

    # 🔥 KAPANIŞTA GELEN HEDEFLERİ ZORLA KONTROL ET
    for d in day_data.values():
        if d.get("hit"):
            continue

        close_price = DAILY_CLOSE_PRICES.get(d["symbol"])
        if not close_price:
            continue

        if close_price >= d["target"]:
            d["hit"] = True
            d["hit_price"] = close_price
            d["hit_time"] = "18:10"
            save_daily_state()

    hits = [d for d in day_data.values() if d.get("hit")]
    fails = [d for d in day_data.values() if not d.get("hit")]

    lines = []
    lines.append("📊 GÜNLÜK BAŞARI RAPORU")
    lines.append(f"📅 {tr_now().strftime('%d.%m.%Y')}")
    lines.append("")
    lines.append(f"📡 Toplam Sinyal: {len(day_data)}")
    lines.append(f"✅ Başarılı: {len(hits)}")
    lines.append(f"❌ Başarısız: {len(fails)}")

    if hits:
        lines.append("")
        lines.append("🎯 BAŞARILI:")
        for d in hits:
            gain = round(((d["hit_price"] - d["entry"]) / d["entry"]) * 100, 2)
            lines.append(f"• {d['symbol']} | {d['algo']} | %{gain}")

    if fails:
        lines.append("")
        lines.append("⛔ HEDEF GELMEYENLER:")
        for d in fails:
            lines.append(f"• {d['symbol']} | {d['algo']}")

    lines.append("")
    lines.append(f"🕒 {tr_now().strftime('%H:%M')}")

    return "\n".join(lines)


# ======================================================
# WEEKLY SUCCESS REPORT (CUMA)
# ======================================================

def build_weekly_success_report():
    w_key = week_key()
    week_data = WEEKLY_SUCCESS_TRACKER.get(w_key, {})

    if not week_data:
        return None

    hits = [d for d in week_data.values() if d.get("hit")]
    fails = [d for d in week_data.values() if not d.get("hit")]

    lines = []
    lines.append("📅 HAFTALIK BAŞARI RAPORU")
    lines.append(f"📆 Hafta: {w_key}")
    lines.append("")
    lines.append(f"📡 Toplam: {len(week_data)}")
    lines.append(f"✅ Başarılı: {len(hits)}")
    lines.append(f"❌ Başarısız: {len(fails)}")

    if hits:
        lines.append("")
        lines.append("🎯 BAŞARILI SİNYALLER:")
        for d in hits:
            base_gain = round(((d["hit_price"] - d["entry"]) / d["entry"]) * 100, 2)

            friday_price = FRIDAY_CLOSE_PRICES.get(d["symbol"])
            friday_gain = None
            if friday_price:
                friday_gain = round(
                    ((friday_price - d["entry"]) / d["entry"]) * 100, 2
                )

            line = (
                f"• {d['symbol']} | {d['algo']} | "
                f"{d['entry_day']} → {d['hit_day']} | "
                f"Hedef: %{base_gain}"
            )

            if friday_gain is not None:
                line += f" | Cuma: %{friday_gain}"

            lines.append(line)

    if fails:
        lines.append("")
        lines.append("⛔ HEDEF GELMEYENLER:")
        for d in fails:
            lines.append(
                f"• {d['symbol']} | {d['algo']}"
            )

    lines.append("")
    lines.append(f"🕒 {tr_now().strftime('%d.%m.%Y %H:%M')}")

    return "\n".join(lines)


# ======================================================
# TELEGRAM FORMAT
# ======================================================

def format_signal_message(signal):
    # ---------- SUCCESS ----------
    if signal.get("category") == "success":
        return "\n".join([
            "🎯 HEDEF GELDİ",
            f"📊 {signal['symbol']}",
            "",
            f"🎯 Giriş: {signal['entry_price']}",
            f"📈 Hedef: {signal['target_price']}",
            f"✅ Gerçekleşen: {signal['hit_price']}",
            "",
            f"💰 Kazanç: %{signal['gain_pct']}",
            "",
            f"⏰ {signal['time']}",
        ])

    lines = []

    # ---------- HEADER ----------
    lines.append(f"📊 {signal['symbol']}")
    lines.append(f"🏷 {signal['title']}")
    lines.append("")

    entry = signal.get("entry_price")
    price = signal.get("price")

    if entry:
        lines.append(f"🎯 Giriş: {entry}")
    lines.append(f"💰 Canlı: {price}")

    lines.append(f"⚡ {signal['action']} | 🧠 {signal['main_algorithm']}")
    lines.append(f"📈 Trend: {signal['ema_trend']}")

    # ---------- TP LEVELS ----------
    if entry:
        tp1 = round(entry * 1.015, 2)
        tp2 = round(entry * 1.03, 2)
        tp3 = round(entry * 1.05, 2)

        lines.append("")
        lines.append("🎯 TP Seviyeleri:")
        lines.append(f"• TP1 (%1.5): {tp1}")
        lines.append(f"• TP2 (%3): {tp2}")
        lines.append(f"• TP3 (%5): {tp3}")

    # ---------- RESISTANCES ----------
    r1h = signal.get("resistance_1h")
    r4h = signal.get("resistance_4h")

    if price and (r1h or r4h):
        lines.append("")
        lines.append("🧱 Dirençler:")

        if r1h:
            pct = round(((r1h - price) / price) * 100, 2)
            lines.append(f"• 1H Direnç: {r1h} (%{pct} kalan)")

        if r4h:
            pct = round(((r4h - price) / price) * 100, 2)
            lines.append(f"• 4H Direnç: {r4h} (%{pct} kalan)")

    # ---------- MOST ----------
    if signal.get("most_1h") or signal.get("most_4h"):
        lines.append("")
        lines.append("🧭 MOST:")

        if signal.get("most_1h"):
            lvl = signal.get("most_1h_level")
            arrow = "⬆️" if signal["most_1h"] == "UP" else "⬇️"
            lines.append(f"• 1H MOST ({lvl}): {arrow}" if lvl else f"• 1H MOST: {arrow}")

        if signal.get("most_4h"):
            lvl = signal.get("most_4h_level")
            arrow = "⬆️" if signal["most_4h"] == "UP" else "⬇️"
            lines.append(f"• 4H MOST ({lvl}): {arrow}" if lvl else f"• 4H MOST: {arrow}")

    # ---------- HELPERS ----------
    if signal.get("helpers_detail"):
        lines.append("")
        lines.append("🧩 Yardımcılar:")
        for h in signal["helpers_detail"]:
            lines.append(f"• [{h['level']}] {h['name']}")

    # ---------- POWER ----------
    if signal.get("power_delta"):
        lines.append("")
        lines.append(
            f"{'🔥' if signal['power_delta'] > 0 else '⚠️'} "
            f"Güç Değişimi: {signal['power_delta']}"
        )

    # ---------- HISTORY ----------
    if signal.get("history"):
        lines.append("")
        lines.append("🕒 Gelişim:")
        for t, msg in signal["history"][-4:]:
            lines.append(f"{t} → {msg}")

    lines.append("")
    lines.append(f"⏰ {signal['time']}")

    return "\n".join(lines)


# ======================================================
# BULK PROCESS
# ======================================================

def process_signals(data):
    out = []

    for item in data:
        try:
            signals = process_symbol_signals(item)
            out.extend(signals)

            symbol = item["symbol"]
            price = item["current_price"]


        except Exception:
            continue

    return out
