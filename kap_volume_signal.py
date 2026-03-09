from datetime import datetime


def detect_kap_volume_momentum(item, kap_cache):

    symbol = item["symbol"]

    if symbol not in kap_cache:
        return None

    tf15 = item["tf"]["15m"]
    df = tf15["df"]

    if df is None or len(df) < 20:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # -------------------------------------------------
    # HACİM PATLAMASI
    # -------------------------------------------------

    vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

    if last["Volume"] < vol_ma * 2.5:
        return None

    # -------------------------------------------------
    # GAP MOMENTUM
    # -------------------------------------------------

    if last["Close"] < prev["Close"] * 1.01:
        return None

    # -------------------------------------------------
    # KAP ZAMAN KONTROL
    # -------------------------------------------------

    kap = kap_cache[symbol]

    minutes = (datetime.now() - kap["time"]).total_seconds() / 60

    if minutes > 3:
        return None

    # -------------------------------------------------
    # SİNYAL
    # -------------------------------------------------

    return {
        "symbol": symbol,
        "title": kap["title"],
        "link": kap["link"]
    }
