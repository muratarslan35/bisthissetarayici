from datetime import datetime
import pandas as pd


def detect_kap_volume_momentum(item, kap_cache):

    symbol = item["symbol"]

    if symbol not in kap_cache:
        return None

    tf15 = item["tf"]["15m"]
    df = tf15["df"]

    if df is None or len(df) < 30:
        return None

    last = df.iloc[-1]

    # -----------------------------
    # HACİM PATLAMASI
    # -----------------------------

    vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

    if last["Volume"] < vol_ma * 2:
        return None

    # -----------------------------
    # VWAP HESABI
    # -----------------------------

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3

    vwap = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()

    last_vwap = vwap.iloc[-1]

    if last["Close"] < last_vwap:
        return None

    # -----------------------------
    # MOMENTUM
    # -----------------------------

    prev_close = df["Close"].iloc[-2]

    momentum = (last["Close"] - prev_close) / prev_close

    if momentum < 0.01:
        return None

    # -----------------------------
    # KAP ZAMAN KONTROLÜ
    # -----------------------------

    kap = kap_cache[symbol]

    minutes = (datetime.now() - kap["time"]).seconds / 60

    if minutes > 5:
        return None

    # -----------------------------
    # SİNYAL
    # -----------------------------

    return {
        "symbol": symbol,
        "title": kap["title"],
        "link": kap["link"]
    }
