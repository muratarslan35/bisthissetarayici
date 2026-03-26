from datetime import datetime
from kap_watchlist_engine import in_watchlist
from bist_market_filters import (
    get_brut_list,
    detect_halt_from_data,
    validate_tradeable_momentum   # ✅ YENİ
)

BRUT_LIST = set()
LAST_FILTER_UPDATE = None


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

        tf15 = item.get("tf", {}).get("15m")
        if not tf15:
            return None

        df = tf15.get("df")
        if df is None or len(df) < 30:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        price = last["Close"]

        # ==================================================
        # 🚀 YENİ: MOMENTUM KALİTE FİLTRESİ (ANA FİX)
        # ==================================================

        ok, phase = validate_tradeable_momentum(df, price)

        if not ok:
            return None  # ❌ GEÇ / PARABOLİK → ELENİR

        # ==================================================
        # RVOL
        # ==================================================

        vol_ma = df["Volume"].rolling(20).mean().iloc[-1]
        if not vol_ma or vol_ma == 0:
            return None

        rvol = last["Volume"] / vol_ma

        threshold = 1.3 if in_watchlist(symbol) else 1.7

        if rvol < threshold:
            return None

        # fake volume filtresi
        if rvol > 6 and abs((last["Close"] - prev["Close"]) / prev["Close"]) < 0.01:
            return None

        # ==================================================
        # VWAP
        # ==================================================

        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()

        if last["Close"] < vwap.iloc[-1]:
            return None

        vwap_dist = (price - vwap.iloc[-1]) / vwap.iloc[-1]

        if vwap_dist > 0.02:  # ❌ çok uzak → geç kaldın
            return None

        # ==================================================
        # MOMENTUM
        # ==================================================

        momentum = (last["Close"] - prev["Close"]) / prev["Close"]

        if momentum < 0.005:
            return None

        # ==================================================
        # CANDLE
        # ==================================================

        body = abs(last["Close"] - last["Open"])
        full = last["High"] - last["Low"]

        if full == 0 or body / full < 0.5:
            return None

        # ==================================================
        # SMART MONEY
        # ==================================================

        big_volume = last["Volume"] > vol_ma * 2.5

        # ==================================================
        # HALT
        # ==================================================

        halt = detect_halt_from_data(item)

        if halt:
            return None  # ❌ HALT varsa sinyal yok

        # ==================================================
        # BRÜT
        # ==================================================

        brut = symbol in BRUT_LIST

        # ==================================================
        # KAP
        # ==================================================

        kap = kap_cache.get(symbol)

        if kap:
            minutes = (datetime.now() - kap["time"]).total_seconds() / 60
            if minutes > 15:
                kap = None

        # ==================================================
        # 🎯 SCORE SYSTEM (YENİ)
        # ==================================================

        score = 0

        # faz
        if phase == "EARLY":
            score += 25
        elif phase == "MID":
            score += 10
        else:
            score -= 20

        # rvol
        if rvol > 3:
            score += 20
        elif rvol > 2:
            score += 10

        # smart money
        if big_volume:
            score += 10

        # momentum gücü
        if momentum > 0.01:
            score += 10

        # ==================================================
        # 🎯 KALİTE
        # ==================================================

        if score >= 50:
            quality = "A+"
        elif score >= 35:
            quality = "A"
        elif score >= 20:
            quality = "B"
        else:
            return None  # ❌ düşük kalite

        # ==================================================
        # RETURN
        # ==================================================

        return {
            "symbol": symbol,
            "title": kap.get("title") if kap else "EDGE MOMENTUM",
            "link": kap.get("link") if kap else None,
            "brut": brut,
            "halt": halt,
            "rvol": round(rvol, 2),
            "smart_money": big_volume,
            "quality": quality,
            "score": score,
            "phase": phase,
            "momentum_pct": round(momentum * 100, 2),
            "vwap_distance": round(vwap_dist * 100, 2)
        }

    except Exception as e:

        print("KAP MOMENTUM ERROR:", e)

        return None
