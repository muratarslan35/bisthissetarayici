from datetime import datetime
from kap_watchlist_engine import in_watchlist
from bist_market_filters import (
    get_brut_list,
    detect_halt_from_data,
    validate_tradeable_momentum,
    detect_pullback_entry
)

BRUT_LIST = set()
LAST_FILTER_UPDATE = None

LAST_SIGNAL_TIME = {}
LAST_SIGNAL_PRICE = {}


def refresh_filters():

    global BRUT_LIST, LAST_FILTER_UPDATE

    now = datetime.now()

    if LAST_FILTER_UPDATE:
        if (now - LAST_FILTER_UPDATE).seconds < 300:
            return

    try:
        brut = get_brut_list()
        BRUT_LIST = set(brut.keys())
    except:
        BRUT_LIST = set()

    LAST_FILTER_UPDATE = now


def detect_kap_volume_momentum(item, kap_cache):

    try:

        refresh_filters()

        symbol = item.get("symbol")
        if not symbol:
            return None

        now = datetime.now()

        tf15 = item.get("tf", {}).get("15m")
        if not tf15:
            return None

        df = tf15.get("df")
        if df is None or len(df) < 30:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ✅ candle fiyatı
        candle_price = last["Close"]

        # ✅ gerçek fiyat
        price = item.get("current_price")

        if not price:
            return None

        # ==================================================
        # 🚀 1️⃣ SPAM BLOCK
        # ==================================================

        if symbol in LAST_SIGNAL_TIME:
            diff = (now - LAST_SIGNAL_TIME[symbol]).seconds
            if diff < 600:
                return None

        if symbol in LAST_SIGNAL_PRICE:
            change = abs(price - LAST_SIGNAL_PRICE[symbol]) / LAST_SIGNAL_PRICE[symbol]
            if change < 0.01:
                return None

        # ==================================================
        # 🚀 2️⃣ MOMENTUM FAZI
        # ==================================================

        ok, phase = validate_tradeable_momentum(df, price)

        if not ok:
            return None

        # ==================================================
        # 🚀 3️⃣ BREAKOUT
        # ==================================================

        prev_high = df["High"].rolling(20).max().iloc[-2]
        is_breakout = price > prev_high

        # ==================================================
        # 🚀 4️⃣ PULLBACK
        # ==================================================

        pullback_ok, pullback_pct = detect_pullback_entry(df, price)

        if not is_breakout and not pullback_ok:
            return None

        entry_type = "BREAKOUT" if is_breakout else "PULLBACK"

        # ==================================================
        # 🚀 ⛔ GEÇ KALMA FİLTRESİ
        # ==================================================

        if abs(price - candle_price) / candle_price > 0.015:
            return None

        # ==================================================
        # 🚀 5️⃣ HACİM
        # ==================================================

        vol_ma = df["Volume"].rolling(20).mean().iloc[-1]
        if not vol_ma or vol_ma == 0:
            return None

        rvol = last["Volume"] / vol_ma

        threshold = 1.3 if in_watchlist(symbol) else 1.7

        if rvol < threshold:
            return None

        if last["Volume"] < vol_ma * 2:
            return None

        # ==================================================
        # 🚀 6️⃣ VWAP
        # ==================================================

        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()

        if price < vwap.iloc[-1]:
            return None

        vwap_dist = (price - vwap.iloc[-1]) / vwap.iloc[-1]

        if vwap_dist > 0.02:
            return None

        # ==================================================
        # 🚀 7️⃣ MOMENTUM
        # ==================================================

        momentum = (price - prev["Close"]) / prev["Close"]

        if momentum < 0.005:
            return None

        # ==================================================
        # 🚀 8️⃣ CANDLE
        # ==================================================

        body = abs(price - last["Open"])
        full = last["High"] - last["Low"]

        if full == 0 or body / full < 0.5:
            return None

        # ==================================================
        # 🚀 9️⃣ SMART MONEY
        # ==================================================

        big_volume = last["Volume"] > vol_ma * 2.5

        # ==================================================
        # 🚀 🔟 HALT
        # ==================================================

        if detect_halt_from_data(item):
            return None

        # ==================================================
        # 🚀 1️⃣1️⃣ BRÜT
        # ==================================================

        brut = symbol in BRUT_LIST

        # ==================================================
        # 🚀 1️⃣2️⃣ KAP
        # ==================================================

        kap = kap_cache.get(symbol)

        if kap:
            minutes = (datetime.now() - kap["time"]).total_seconds() / 60
            if minutes > 15:
                kap = None

        # ==================================================
        # 🚀 1️⃣3️⃣ SCORE
        # ==================================================

        score = 0

        if phase == "ERKEN":
            score += 30
        elif phase == "ORTA":
            score += 15
        else:
            score -= 20

        if rvol > 3:
            score += 20
        elif rvol > 2:
            score += 10

        if big_volume:
            score += 10

        if momentum > 0.01:
            score += 10

        if is_breakout:
            score += 15

        if pullback_ok:
            score += 25

        # ==================================================
        # 🚀 1️⃣4️⃣ KALİTE
        # ==================================================

        if score >= 65:
            quality = "A+"
        elif score >= 50:
            quality = "A"
        elif score >= 35:
            quality = "B"
        else:
            return None

        # ==================================================
        # 🚀 🎯 ELİT FİLTRE (YENİ)
        # ==================================================

        if quality not in ["A+", "A"]:
            return None

        if phase != "ERKEN":
            return None

        # ==================================================
        # 🚀 CACHE
        # ==================================================

        LAST_SIGNAL_TIME[symbol] = now
        LAST_SIGNAL_PRICE[symbol] = price

        # ==================================================
        # RETURN
        # ==================================================

        return {
            "symbol": symbol,
            "entry_price": round(price, 2),
            "title": kap.get("title") if kap else "EDGE MOMENTUM",
            "link": kap.get("link") if kap else None,
            "brut": brut,
            "rvol": round(rvol, 2),
            "smart_money": big_volume,
            "quality": quality,
            "score": score,
            "phase": phase,
            "entry_type": entry_type,
            "pullback_pct": pullback_pct,
            "momentum_pct": round(momentum * 100, 2),
            "vwap_distance": round(vwap_dist * 100, 2)
        }

    except Exception as e:

        print("KAP MOMENTUM ERROR:", e)

        return None
