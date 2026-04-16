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
            progress=False,
            auto_adjust=True,
            threads=False
        )

        if df is None or len(df) < 10:
            return None

        # --------------------------------------------------
        # 💥 MULTIINDEX FIX (EN KRİTİK)
        # --------------------------------------------------
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # --------------------------------------------------
        # KOLON DÜZENLE
        # --------------------------------------------------
        df.columns = [c.lower() for c in df.columns]

        required_cols = ["open", "high", "low", "close", "volume"]

        if not all(col in df.columns for col in required_cols):
            print("❌ KOLON HATALI:", df.columns)
            return None

        df = df[required_cols]
        # 🔥 TIMEZONE FIX (KRİTİK)
        df.index = df.index.tz_localize(None)

        # --------------------------------------------------
        # 🔥 CANLI FİYAT ENJEKTE
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
        # 🔥 SON 40 BAR (GRAFİK İÇİN)
        # --------------------------------------------------
        df = df.tail(40)

        # --------------------------------------------------
        # CACHE SAVE
        # --------------------------------------------------
        CACHE[cache_key] = (df, datetime.now())

        return df

    except Exception as e:
        print("YF ERROR:", symbol, e)
        return None
