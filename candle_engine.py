import yfinance as yf
import pandas as pd
from datetime import datetime

CACHE = {}

# ======================================================
# 🔥 CORE FETCH (GENERIC)
# ======================================================
def _fetch_df(symbol, interval, period, live_price=None, cache_key=None):

    try:
        symbol = symbol.replace(".IS", "") + ".IS"

        # --------------------------------------------------
        # CACHE
        # --------------------------------------------------
        if cache_key in CACHE:
            df, ts = CACHE[cache_key]

            if (datetime.now() - ts).seconds < 60:

                if live_price is not None and len(df) > 0:
                    df = df.copy()
                    last_idx = df.index[-1]

                    df.at[last_idx, "close"] = live_price
                    df.at[last_idx, "high"] = max(df.at[last_idx, "high"], live_price)
                    df.at[last_idx, "low"] = min(df.at[last_idx, "low"], live_price)

                return df

        # --------------------------------------------------
        # YFINANCE
        # --------------------------------------------------
        df = yf.download(
            symbol,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=True,
            threads=False
        )

        if df is None or len(df) < 10:
            print(f"❌ DATA YOK: {symbol} {interval}")
            return None

        # --------------------------------------------------
        # MULTIINDEX FIX
        # --------------------------------------------------
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # --------------------------------------------------
        # COLUMN FIX
        # --------------------------------------------------
        df.columns = [c.lower() for c in df.columns]

        required = ["open", "high", "low", "close", "volume"]

        if not all(c in df.columns for c in required):
            print("❌ KOLON HATALI:", df.columns)
            return None

        df = df[required]

        # --------------------------------------------------
        # TIME FIX
        # --------------------------------------------------
        try:
            df.index = df.index.tz_localize(None)
        except:
            pass

        # --------------------------------------------------
        # LIVE PRICE INJECT
        # --------------------------------------------------
        if live_price is not None and len(df) > 0:
            try:
                last_idx = df.index[-1]

                df.at[last_idx, "close"] = live_price
                df.at[last_idx, "high"] = max(df.at[last_idx, "high"], live_price)
                df.at[last_idx, "low"] = min(df.at[last_idx, "low"], live_price)

            except Exception as e:
                print("LIVE PRICE ERROR:", e)

        # --------------------------------------------------
        # 🔥 BAR SAYISI (GENİŞ GRAFİK)
        # --------------------------------------------------
        df = df.tail(120)

        # --------------------------------------------------
        # 🔥 EMA EKLE (PRO)
        # --------------------------------------------------
        try:
            df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
            df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        except Exception as e:
            print("EMA ERROR:", e)

        # --------------------------------------------------
        # CACHE SAVE
        # --------------------------------------------------
        CACHE[cache_key] = (df, datetime.now())

        return df

    except Exception as e:
        print("YF ERROR:", symbol, interval, e)
        return None


# ======================================================
# 🔥 15M
# ======================================================
def get_15m_df(symbol, live_price=None):

    return _fetch_df(
        symbol=symbol,
        interval="15m",
        period="1d",
        live_price=live_price,
        cache_key=f"{symbol}_15m"
    )


# ======================================================
# 🔥 1H (KRİTİK)
# ======================================================
def get_1h_df(symbol, live_price=None):

    return _fetch_df(
        symbol=symbol,
        interval="60m",
        period="5d",   # 🔥 kritik (1d yetmez!)
        live_price=live_price,
        cache_key=f"{symbol}_1h"
    )
