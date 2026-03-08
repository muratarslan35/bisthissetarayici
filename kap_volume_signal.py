from datetime import datetime

def detect_kap_volume_momentum(item,kap_cache):

    symbol=item["symbol"]

    if symbol not in kap_cache:
        return None

    tf15=item["tf"]["15m"]
    df=tf15["df"]

    if df is None or len(df)<20:
        return None

    last=df.iloc[-1]

    vol_ma=df["Volume"].rolling(20).mean().iloc[-1]

    if last["Volume"] < vol_ma*2:
        return None

    kap=kap_cache[symbol]

    minutes=(datetime.now()-kap["time"]).seconds/60

    if minutes>3:
        return None

    return {
        "symbol":symbol,
        "title":kap["title"],
        "link":kap["link"]
    }
