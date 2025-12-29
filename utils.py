import yfinance as yf
from datetime import datetime, timezone, timedelta
import pandas as pd

FALLBACK_SYMBOLS = ["GARAN.IS","AKBNK.IS","ASELS.IS","THYAO.IS"]  # fallback dosya listesi

def to_tr_timezone(dt):
    return dt.astimezone(tz=timezone(timedelta(hours=3)))

def get_fallback_symbols():
    return FALLBACK_SYMBOLS

def fetch_yf_ohlcv(symbol):
    df = yf.download(symbol, period="7d", interval="15m")
    if df.empty:
        raise Exception("Veri alınamadı")
    return {
        "close": df["Close"].tolist(),
        "open": df["Open"].tolist(),
        "high": df["High"].tolist(),
        "low": df["Low"].tolist(),
        "volume": df["Volume"].tolist()
    }

def calculate_rsi_ema(ohlcv):
    import numpy as np
    close = ohlcv["close"]
    df = pd.DataFrame({"close": close})
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["delta"] = df["close"].diff()
    df["gain"] = df["delta"].clip(lower=0)
    df["loss"] = -df["delta"].clip(upper=0)
    df["avg_gain"] = df["gain"].rolling(14).mean()
    df["avg_loss"] = df["loss"].rolling(14).mean()
    df["rs"] = df["avg_gain"]/df["avg_loss"]
    df["rsi"] = 100 - (100/(1+df["rs"]))
    
    # EMA trend
    ema_trend = "↑" if df["ema9"].iloc[-1]>df["ema21"].iloc[-1] else "↓"
    
    # RSI 1h & 4h approximation (hayali mumlar)
    rsi_1h = df["rsi"].rolling(4).mean().iloc[-1]
    rsi_4h = df["rsi"].rolling(16).mean().iloc[-1]
    
    # Güçlü AL mantığı
    signal = False
    strength = 0
    algorithms = []
    if df["ema9"].iloc[-1]>df["ema21"].iloc[-1] and rsi_1h<70:
        signal = True
        strength = 7
        algorithms.append("l2")
    
    return {
        "ema_trend": ema_trend,
        "rsi_1h": round(rsi_1h,2),
        "rsi_4h": round(rsi_4h,2),
        "signal": signal,
        "strength": strength,
        "algorithms": algorithms
    }
