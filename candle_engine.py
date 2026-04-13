import yfinance as yf
import pandas as pd
from datetime import datetime

CACHE = {}

def get_15m_df(symbol, live_price=None):

    try:
        symbol = symbol.replace(".IS", "") + ".IS"

        cache_key = symbol

        # --------------------------------------------------
        # CACHE (60 sn)
        # --------------------------------------------------
        if cache_key in CACHE:
            df, ts = CACHE[cache_key]

            if (datetime.now() - ts).seconds < 60:
                # 🔥 canlı fiyat varsa cache'e de uygula
                if live_price is not None and len(df) > 0:
                    df = df.copy()
                    last_idx = df.index[-1]

                    df.at[last_idx, "close"] = live_price
                    df.at[last_idx, "high"] = max(df.at[last_idx, "high"], live_price)
                    df.at[last_idx, "low"] = min(df.at[last_idx, "low"], live_price)

                return df

        # --------------------------------------------------
        # YFINANCE DATA
        # --------------------------------------------------
        df = yf.download(
            symbol,
            interval="15m",
            period="1d",
            progress=False
        )

        if df is None or len(df) < 10:
            return None

        # --------------------------------------------------
        # KOLON DÜZENLE
        # --------------------------------------------------
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        df = df[["open", "high", "low", "close", "volume"]]

        # --------------------------------------------------
        # 🔥 CANLI FİYAT ENJEKTE (EN KRİTİK)
        # --------------------------------------------------
        if live_price is not None:
            try:
                last_idx = df.index[-1]

                df.at[last_idx, "close"] = live_price
                df.at[last_idx, "high"] = max(df.at[last_idx, "high"], live_price)
                df.at[last_idx, "low"] = min(df.at[last_idx, "low"], live_price)
            except Exception as e:
                print("LIVE PRICE ERROR:", e)

        # --------------------------------------------------
        # CACHE SAVE
        # --------------------------------------------------
        CACHE[cache_key] = (df, datetime.now())

        return df

    except Exception as e:
        print("YF ERROR:", symbol, e)
        return None
