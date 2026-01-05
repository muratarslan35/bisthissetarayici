from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np

from utils import (
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
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

# 🔹 GÜNLÜK BAŞARI (HER SABAH SIFIRLANIR)
DAILY_SUCCESS_TRACKER = {}

# 🔹 HAFTALIK TAKİP (PAZARTESİ BAŞLAR – CUMA RAPOR)
WEEKLY_SUCCESS_TRACKER = {}

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

# ======================================================
# RESET MEKANİZMALARI
# ======================================================

def reset_daily_if_needed():
    key = today_key()
    if key not in DAILY_SUCCESS_TRACKER:
        DAILY_SUCCESS_TRACKER.clear()
        DAILY_SUCCESS_TRACKER[key] = {}

def reset_weekly_if_needed():
    key = week_key()
    if key not in WEEKLY_SUCCESS_TRACKER:
        WEEKLY_SUCCESS_TRACKER.clear()
        WEEKLY_SUCCESS_TRACKER[key] = {}

# ======================================================
# HELPER SEVİYELERİ
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

    # ORDER BLOCK / L2-L3
    df15 = tf15.get("df")
    if df15 is not None:
        if detect_three_peaks(df15["Close"]):
            helpers.append(("3LÜ TEPE", 8))
        if detect_order_block(df15):
            helpers.append(("ORDER BLOCK", 15))
        helpers.extend(detect_l2_l3_l4(df15, item["current_price"]))

    # 1H KIRILIM
    if tf1h and detect_support_resistance_break(tf1h["df"]):
        helpers.append(("1H YAPISAL KIRILIM", 20))

    # 4H KIRILIM
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

    if not (is_green(tf1d["df"], -2) and is_green(tf1d["df"], -1)):
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

    main = super_kombine_signal(item) or kombine_signal(item)
    if not main:
        return []

    algo = main["main_type"]

    helpers = helper_indicators(item)
    helper_map = {h[0]: h[1] for h in helpers}
    helper_names = set(helper_map.keys())

    total_power = sum(v for v in helper_map.values() if isinstance(v, (int, float)))

    key = (symbol, algo)
    prev = LAST_SIGNAL_STATE.get(key, {})

    prev_power = prev.get("power", 0)
    power_delta = total_power - prev_power

    prev_helpers = set(prev.get("helpers", []))
    added_helpers = list(helper_names - prev_helpers)
    removed_helpers = list(prev_helpers - helper_names)

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

    levels = {"A": 0, "B": 0, "C": 0}
    for h in helper_names:
        lvl = HELPER_LEVELS.get(h)
        if lvl:
            levels[lvl] += 1

    if levels["A"] >= 1:
        action, category, title = "GÜÇLÜ AL", "strong", "🚀 GÜÇLÜ AL – A Seviye"
    elif levels["B"] >= 1:
        action, category, title = "AL", "combo", "📈 AL – B Seviye"
    elif levels["C"] >= 1:
        action, category, title = "İZLE", "watch", "👀 İZLE"
    else:
        return []

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

    if in_repeat_block(symbol, algo) and not (
        strengthened or weakened or most_upgrade or most_downgrade
    ):
        return []

    mark_sent(symbol, algo)

    now_h = tr_now().strftime("%H:%M")
    history = prev.get("history", [(now_h, f"{algo} sinyal")])

    if added_helpers:
        history.append((now_h, f"Eklendi: {', '.join(added_helpers)}"))
    if removed_helpers:
        history.append((now_h, f"Çıktı: {', '.join(removed_helpers)}"))

    LAST_SIGNAL_STATE[key] = {
        "power": total_power,
        "helpers": list(helper_names),
        "most_4h": most_4h,
        "history": history,
    }

    r1h = get_last_resistance(tf1h["df"]) if tf1h else None
    r4h = get_last_resistance(tf4h["df"]) if tf4h else None

    today = tr_now().date()
    entry_price = None
    if (symbol, algo) in SUCCESS_TRACKER.get(today, {}):
        entry_price = SUCCESS_TRACKER[today][(symbol, algo)].get("entry")

    signal = {
        "symbol": symbol,
        "entry_price": fmt(entry_price),
        "price": fmt(price),
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
            {"name": h, "level": HELPER_LEVELS[h], "desc": HELPER_DESCRIPTIONS.get(h, "")}
            for h in helper_names if h in HELPER_LEVELS
        ],
        "history": history,
        "time": tr_now().strftime("%H:%M:%S"),
        "resistance_1h": fmt(r1h),
        "resistance_4h": fmt(r4h),
        "power": total_power,
        "power_delta": power_delta,
        "most_1h": most_1h,
        "most_4h": most_4h,
    }

    register_success_candidate(signal)
    return [signal]

# ======================================================
# SUCCESS TRACK (DAILY + WEEKLY ALTYAPI)
# ======================================================

def register_success_candidate(signal):
    today = tr_now().date()
    SUCCESS_TRACKER.setdefault(today, {})

    key = (signal["symbol"], signal["main_algorithm"])

    # Aynı gün aynı sinyal varsa ENTRY overwrite yok
    if key in SUCCESS_TRACKER[today]:
        return

    entry_price = signal.get("price")
    if entry_price is None:
        return

    SUCCESS_TRACKER[today][key] = {
        "symbol": signal["symbol"],
        "algo": signal["main_algorithm"],
        "helpers": signal.get("helpers", []),
        "entry": entry_price,
        "target": entry_price * (1 + TARGET_PCT),
        "hit": False,
        "entry_time": tr_now().strftime("%H:%M:%S"),
        "entry_date": today,
    }


# ======================================================
# SUCCESS TARGET UPDATE
# ======================================================

def update_success_targets(symbol, price):
    today = tr_now().date()
    success_signals = []

    day_data = SUCCESS_TRACKER.get(today, {})
    if not day_data:
        return []

    for (sym, algo), d in day_data.items():
        if d["hit"]:
            continue
        if sym != symbol:
            continue

        if price >= d["target"]:
            d["hit"] = True
            d["hit_price"] = price
            d["hit_time"] = tr_now().strftime("%H:%M:%S")

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

    return success_signals


# ======================================================
# TELEGRAM FORMAT
# ======================================================

def format_signal_message(signal):
    # ---------------- SUCCESS ----------------
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

    # ---------------- NORMAL ----------------
    lines = []
    lines.append(f"📊 {signal['symbol']}")
    lines.append(f"🏷 {signal['title']}")
    lines.append("")

    if signal.get("entry_price"):
        lines.append(f"🎯 Giriş Fiyatı: {signal['entry_price']}")
    lines.append(f"💰 Canlı Fiyat: {signal['price']}")

    lines.append(f"⚡ Sinyal: {signal['action']}")
    lines.append(f"🧠 Algo: {signal['main_algorithm']}")
    lines.append(f"📈 Trend: {signal['ema_trend']}")

    if signal.get("most_1h") or signal.get("most_4h"):
        lines.append("")
        lines.append("🧭 MOST:")
        if signal.get("most_1h"):
            lines.append(f"• 1H: {'⬆️' if signal['most_1h']=='UP' else '⬇️'}")
        if signal.get("most_4h"):
            lines.append(f"• 4H: {'⬆️' if signal['most_4h']=='UP' else '⬇️'}")

    if signal.get("resistance_1h") or signal.get("resistance_4h"):
        lines.append("")
        lines.append("🎯 Dirençler:")
        if signal.get("resistance_1h"):
            lines.append(f"• 1H: {signal['resistance_1h']}")
        if signal.get("resistance_4h"):
            lines.append(f"• 4H: {signal['resistance_4h']}")

    helpers = signal.get("helpers_detail", [])
    if helpers:
        lines.append("")
        lines.append("🧩 Yardımcılar:")
        for h in helpers:
            lines.append(f"• [{h['level']}] {h['name']}")

    if signal.get("power_delta"):
        lines.append("")
        lines.append(
            f"{'🔥' if signal['power_delta']>0 else '⚠️'} "
            f"Güç Değişimi: {signal['power_delta']}"
        )

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
            # Normal sinyaller
            signals = process_symbol_signals(item)
            out.extend(signals)

            # Başarı kontrolü
            symbol = item["symbol"]
            price = item["current_price"]

            success_hits = update_success_targets(symbol, price)
            out.extend(success_hits)

        except Exception:
            continue

    return out
# ======================================================
# DAILY SUCCESS REPORT
# ======================================================

def build_daily_success_report():
    today = tr_now().date()
    day_data = SUCCESS_TRACKER.get(today, {})

    if not day_data:
        return "📊 BUGÜN BAŞARI RAPORU\n\n❌ Bugün takip edilen sinyal yok."

    total = len(day_data)
    hits = [d for d in day_data.values() if d.get("hit")]
    fails = [d for d in day_data.values() if not d.get("hit")]

    hit_count = len(hits)
    fail_count = len(fails)

    # Kazanç hesapları
    gains = []
    for d in hits:
        entry = d.get("entry")
        hit_price = d.get("hit_price")
        if entry and hit_price:
            gains.append(((hit_price - entry) / entry) * 100)

    avg_gain = round(sum(gains) / len(gains), 2) if gains else 0
    max_gain = round(max(gains), 2) if gains else 0

    # Algoritma istatistiği
    algo_stats = {}
    for d in hits:
        algo = d.get("algo")
        algo_stats[algo] = algo_stats.get(algo, 0) + 1

    lines = []
    lines.append("📊 GÜNLÜK BAŞARI RAPORU")
    lines.append(f"📅 Tarih: {today}")
    lines.append("")
    lines.append(f"📡 Toplam Sinyal: {total}")
    lines.append(f"✅ Başarılı: {hit_count}")
    lines.append(f"❌ Başarısız: {fail_count}")
    lines.append("")
    lines.append(f"📈 Ortalama Kazanç: %{avg_gain}")
    lines.append(f"🚀 Maksimum Kazanç: %{max_gain}")

    if algo_stats:
        lines.append("")
        lines.append("🧠 Algoritma Başarıları:")
        for algo, cnt in algo_stats.items():
            lines.append(f"• {algo}: {cnt} adet")

    if hits:
        lines.append("")
        lines.append("🎯 BAŞARILI SİNYALLER:")
        for d in hits:
            entry = d.get("entry")
            hit_price = d.get("hit_price")
            gain = round(((hit_price - entry) / entry) * 100, 2)
            lines.append(
                f"• {d['symbol']} | {d['algo']} | %{gain}"
            )

    if fails:
        lines.append("")
        lines.append("⛔ HEDEFE ULAŞMAYANLAR:")
        for d in fails:
            lines.append(
                f"• {d['symbol']} | {d['algo']}"
            )

    lines.append("")
    lines.append("🕒 Rapor saati: " + tr_now().strftime("%H:%M"))

    return "\n".join(lines)
