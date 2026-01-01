import time
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

from utils import (
    BIST_SYMBOLS,
    resolve_symbols,
    fetch_tradingview_price,
    nearest_support_resistance_from_history
)

MAX_LOOKBACK = {
    "15m": "5d",
    "30m": "5d",
    "1h": "10d",
    "1d": "6mo"
}

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def resample_df(df, rule):
    return df.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

def fetch_yf(symbol, interval):
    try:
        df = yf.download(
            symbol.replace(".IS", ""),
            interval=interval,
            period=MAX_LOOKBACK.get(interval, "5d"),
            progress=False,
            auto_adjust=False
        )
        if df.empty:
            return None

        df = df.rename_axis("Datetime").reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df.set_index("Datetime", inplace=True)
        return df
    except Exception:
        return None

def build_tf_data(symbol):
    tf = {}

    base_df = fetch_yf(symbol, "15m") or fetch_yf(symbol, "30m")
    if base_df is None:
        return None

    base_df["ema20"] = compute_ema(base_df["Close"], 20)
    base_df["ema50"] = compute_ema(base_df["Close"], 50)
    base_df["ema200"] = compute_ema(base_df["Close"], 200)
    base_df["rsi"] = compute_rsi(base_df["Close"])

    base_df["volume_ma"] = base_df["Volume"].rolling(20).mean()
    base_df["volume_ok"] = base_df["Volume"] > base_df["volume_ma"] * 1.5

    tf["15m"] = {
        "ema20": float(base_df["ema20"].iloc[-1]),
        "ema50": float(base_df["ema50"].iloc[-1]),
        "ema200": float(base_df["ema200"].iloc[-1]),
        "rsi": float(base_df["rsi"].iloc[-1]),
        "volume_ok": bool(base_df["volume_ok"].iloc[-1]),
        "df": base_df
    }

    for k, rule in [("1h", "1H"), ("4h", "4H")]:
        d = resample_df(base_df, rule)
        if not d.empty:
            d["ema20"] = compute_ema(d["Close"], 20)
            d["ema50"] = compute_ema(d["Close"], 50)
            tf[k] = {
                "ema20": float(d["ema20"].iloc[-1]),
                "ema50": float(d["ema50"].iloc[-1]),
                "df": d
            }

    df1d = fetch_yf(symbol, "1d")
    if df1d is not None:
        df1d["ema50"] = compute_ema(df1d["Close"], 50)
        df1d["ema200"] = compute_ema(df1d["Close"], 200)
        tf["1d"] = {
            "ema50": float(df1d["ema50"].iloc[-1]),
            "ema200": float(df1d["ema200"].iloc[-1])
        }

    return tf

def fetch_bist_data(symbol_data=None):
    results = []
    symbols = resolve_symbols(symbol_data)

    for symbol in symbols:
        try:
            price = fetch_tradingview_price(symbol)
            if not price:
                continue

            tf = build_tf_data(symbol)
            if not tf or "15m" not in tf or "1h" not in tf or "4h" not in tf:
                continue

            results.append({
                "symbol": symbol,
                "current_price": price,
                "tf": tf,
                "fetched_at": datetime.now(timezone.utc)
            })

            time.sleep(0.15)
        except Exception:
            continue

    return results
