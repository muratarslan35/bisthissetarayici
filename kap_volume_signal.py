from datetime import datetime
from kap_watchlist_engine import in_watchlist
from bist_market_filters import get_brut_list

# 🔥 HALT SAFE IMPORT
try:
    from bist_market_filters import get_halt_list
except:
    def get_halt_list():
        return set()

BRUT_LIST = {}
HALT_LIST = set()
LAST_FILTER_UPDATE = None


# ------------------------------------------------
# FILTER UPDATE (ULTRA SAFE)
# ------------------------------------------------

def refresh_filters():

    global BRUT_LIST, HALT_LIST, LAST_FILTER_UPDATE

    now = datetime.now()

    try:

        # CACHE
        if LAST_FILTER_UPDATE:
            diff = (now - LAST_FILTER_UPDATE).seconds
            if diff < 300:
                return

        # -----------------------
        # BRÜT
        # -----------------------
        try:
            brut = get_brut_list()
            if isinstance(brut, dict):
                BRUT_LIST = brut
        except Exception as e:
            print("⚠ BRUT FILTER FAIL:", e)

        # -----------------------
        # HALT (DEVRE KESİCİ)
        # -----------------------
        try:
            halt = get_halt_list()
            if isinstance(halt, (set, list)):
                HALT_LIST = set(halt)
        except Exception as e:
            print("⚠ HALT FILTER FAIL:", e)

        LAST_FILTER_UPDATE = now

    except Exception as e:
        print("🔥 refresh_filters KRİTİK:", e)


# ------------------------------------------------
# MAIN SIGNAL (PRO SAFE)
# ------------------------------------------------

def detect_kap_volume_momentum(item, kap_cache):

    try:

        refresh_filters()

        symbol = item.get("symbol")

        if not symbol:
            return None

        if symbol not in kap_cache:
            return None

        tf15 = item.get("tf", {}).get("15m")
        if not tf15:
            return None

        df = tf15.get("df")

        if df is None or len(df) < 30:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ------------------------------------------------
        # RELATIVE VOLUME
        # ------------------------------------------------

        vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

        if not vol_ma or vol_ma == 0:
            return None

        rvol = last["Volume"] / vol_ma

        threshold = 1.4 if in_watchlist(symbol) else 1.7

        if rvol < threshold:
            return None

        # ------------------------------------------------
        # VWAP
        # ------------------------------------------------

        typical = (df["High"] + df["Low"] + df["Close"]) / 3

        vwap = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()

        last_vwap = vwap.iloc[-1]

        if last["Close"] < last_vwap:
            return None

        # ------------------------------------------------
        # MOMENTUM
        # ------------------------------------------------

        momentum = (last["Close"] - prev["Close"]) / prev["Close"]

        if momentum < 0.006:
            return None

        # ------------------------------------------------
        # CANDLE STRENGTH
        # ------------------------------------------------

        body = abs(last["Close"] - last["Open"])
        full = last["High"] - last["Low"]

        if full == 0:
            return None

        if body / full < 0.5:
            return None

        # ------------------------------------------------
        # SMART MONEY
        # ------------------------------------------------

        big_volume = False

        if last["Volume"] > vol_ma * 2.5:
            big_volume = True

        # ------------------------------------------------
        # KAP TIME
        # ------------------------------------------------

        kap = kap_cache.get(symbol)

        if not kap or "time" not in kap:
            return None

        minutes = (datetime.now() - kap["time"]).total_seconds() / 60

        if minutes > 10:
            return None

        # ------------------------------------------------
        # MARKET FILTER
        # ------------------------------------------------

        brut = symbol in BRUT_LIST
        halt = symbol in HALT_LIST

        return {
            "symbol": symbol,
            "title": kap.get("title"),
            "link": kap.get("link"),
            "brut": brut,
            "halt": halt,
            "rvol": round(rvol, 2),
            "smart_money": big_volume
        }

    except Exception as e:

        print(f"🔥 KAP SIGNAL ERROR ({item.get('symbol')}):", e)

        return None
