from datetime import datetime
from kap_watchlist_engine import in_watchlist
from bist_market_filters import get_brut_list

BRUT_LIST=set()
HALT_LIST=set()
LAST_FILTER_UPDATE=None


# ------------------------------------------------
# FILTER UPDATE
# ------------------------------------------------

def refresh_filters():

    global BRUT_LIST,HALT_LIST,LAST_FILTER_UPDATE

    now=datetime.now()

    if LAST_FILTER_UPDATE:

        diff=(now-LAST_FILTER_UPDATE).seconds

        if diff<300:
            return

    BRUT_LIST=get_brut_list()
    HALT_LIST=get_halt_list()

    LAST_FILTER_UPDATE=now


# ------------------------------------------------
# MAIN SIGNAL
# ------------------------------------------------

def detect_kap_volume_momentum(item,kap_cache):

    refresh_filters()

    symbol=item["symbol"]

    if symbol not in kap_cache:
        return None

    tf15=item["tf"]["15m"]
    df=tf15["df"]

    if df is None or len(df)<30:
        return None

    last=df.iloc[-1]
    prev=df.iloc[-2]

    # ------------------------------------------------
    # RELATIVE VOLUME
    # ------------------------------------------------

    vol_ma=df["Volume"].rolling(20).mean().iloc[-1]

    if vol_ma==0:
        return None

    rvol=last["Volume"]/vol_ma

    threshold=1.4 if in_watchlist(symbol) else 1.7

    if rvol<threshold:
        return None


    # ------------------------------------------------
    # VWAP
    # ------------------------------------------------

    typical=(df["High"]+df["Low"]+df["Close"])/3

    vwap=(typical*df["Volume"]).cumsum()/df["Volume"].cumsum()

    last_vwap=vwap.iloc[-1]

    if last["Close"]<last_vwap:
        return None


    # ------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------

    momentum=(last["Close"]-prev["Close"])/prev["Close"]

    if momentum<0.006:
        return None


    # ------------------------------------------------
    # CANDLE STRENGTH
    # ------------------------------------------------

    body=abs(last["Close"]-last["Open"])
    full=last["High"]-last["Low"]

    if full==0:
        return None

    if body/full<0.5:
        return None


    # ------------------------------------------------
    # SMART MONEY (BÜYÜK HACİM)
    # ------------------------------------------------

    big_volume=False

    if last["Volume"]>vol_ma*2.5:
        big_volume=True


    # ------------------------------------------------
    # KAP ZAMAN
    # ------------------------------------------------

    kap=kap_cache[symbol]

    minutes=(datetime.now()-kap["time"]).total_seconds()/60

    if minutes>10:
        return None


    # ------------------------------------------------
    # MARKET FILTER
    # ------------------------------------------------

    brut=symbol in BRUT_LIST
    halt=symbol in HALT_LIST


    return {
        "symbol":symbol,
        "title":kap["title"],
        "link":kap["link"],
        "brut":brut,
        "halt":halt,
        "rvol":round(rvol,2),
        "smart_money":big_volume
    }
