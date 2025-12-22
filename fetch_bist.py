import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

from utils import (
    FALLBACK_SYMBOLS,
    calculate_rsi,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
    to_tr_timezone,
)

# ==================================================
# TRADINGVIEW PSEUDO LIVE PRICE (CACHE'Lİ)
# ==================================================
_TV_CACHE = {}
_TV_CACHE_TTL = 60  # saniye

def tv_live_price(symbol):
    now = time.time()
    c = _TV_CACHE.get(symbol)
    if c and now - c["ts"] < _TV_CACHE_TTL:
        return c["price"]

    try:
        r = requests.get(
            "https://scanner.tradingview.com/symbol",
            params={"symbol": f"BIST:{symbol}"},
            timeout=4
        )
        js = r.json()
        price = js.get("price")
        if price:
            _TV_CACHE[symbol] = {"price": float(price), "ts": now}
            return float(price)
    except Exception:
        pass
    return None


# ==================================================
# EMA
# ==================================================
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


# ==================================================
# SAFE YFINANCE
# ==================================================
def yf_download_safe(ticker, period, interval):
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        return df.dropna(how="all")
    except Exception:
        return None


# ==================================================
# BIST SYMBOLS
# ==================================================
def get_bist_symbols():
    try:
        url = "https://api.isyatirim.com.tr/index/indexsectorperformance"
        r = requests.get(url, timeout=6)
        js = r.json()
        out = []
        for item in js:
            if item.get("indexCode") in ("XU030", "XU100"):
                for c in item.get("components", []):
                    s = c.get("symbol")
                    if s:
                        out.append(s if s.endswith(".IS") else s + ".IS")
        return list(dict.fromkeys(out))
    except Exception:
        return FALLBACK_SYMBOLS.copy()


# ==================================================
# TF INDICATORS (PSEUDO LIVE PATCH)
# ==================================================
def fetch_timeframe_indicators(df, symbol=None):
    out = {}
    if df is None or df.empty:
        return out

    close = df["Close"].copy()

    # 🔥 pseudo-live close override
    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live:
            close.iloc[-1] = live

    ema20 = calculate_ema(close, 20)
    ema50 = calculate_ema(close, 50)
    ema100 = calculate_ema(close, 100)
    ema200 = calculate_ema(close, 200)

    out["last_close"] = float(close.iloc[-1])
    out["last_open"] = float(df["Open"].iloc[-1])
    out["last_green"] = out["last_close"] > out["last_open"]
    out["ema20"] = float(ema20.iloc[-1])
    out["ema50"] = float(ema50.iloc[-1])
    out["ema100"] = float(ema100.iloc[-1])
    out["ema200"] = float(ema200.iloc[-1])
    out["rsi"] = float(calculate_rsi(close).iloc[-1])

    try:
        out["volume"] = int(df["Volume"].iloc[-1])
        out["volume_avg_5"] = int(df["Volume"].iloc[-6:-1].mean())
        out["volume_ok"] = out["volume"] > out["volume_avg_5"]
    except Exception:
        pass

    try:
        s_break, r_break = detect_support_resistance_break(df)
        out["support_break"] = s_break
        out["resistance_break"] = r_break
    except Exception:
        out["support_break"] = False
        out["resistance_break"] = False

    return out


# ==================================================
# FETCH ONE SYMBOL
# ==================================================
def fetch_one_symbol(sym):
    df_15 = yf_download_safe(sym, "7d", "15m")
    if df_15 is None:
        raise ValueError("no 15m")

    df_1h = yf_download_safe(sym, "14d", "60m")

    # ✅ BURASI DÜZELTİLDİ
    df_4h = yf_download_safe(sym, "60d", "4h")

    df_1d = yf_download_safe(sym, "120d", "1d")

    tf15 = fetch_timeframe_indicators(df_15, sym)
    tf1h = fetch_timeframe_indicators(df_1h)
    tf4h = fetch_timeframe_indicators(df_4h)
    tf1d = fetch_timeframe_indicators(df_1d)

    price = tf15.get("last_close")
    ns, nr = nearest_support_resistance_from_history(df_15)
    three_peak = detect_three_peaks(df_15["Close"])

    return {
        "symbol": sym.replace(".IS", ""),
        "current_price": price,
        "RSI": tf15.get("rsi"),
        "volume": tf15.get("volume"),
        "three_peak_break": three_peak,
        "support_break": tf15.get("support_break"),
        "resistance_break": tf15.get("resistance_break"),
        "nearest_support": ns,
        "nearest_resistance": nr,
        "tf": {
            "15m": tf15,
            "1h": tf1h,
            "4h": tf4h,
            "1d": tf1d
        }
    }


# ==================================================
# FETCH ALL
# ==================================================
def fetch_bist_data():
    out = []
    for s in get_bist_symbols():
        try:
            out.append(fetch_one_symbol(s))
        except Exception:
            continue
        time.sleep(0.15)
    return out
