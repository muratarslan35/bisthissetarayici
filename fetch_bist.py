import time
import os
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

from utils import (
    calculate_rsi,
    calculate_ema,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
)

from fallback_manager import (
    get_active_symbols,
    report_success,
    report_no_data,
    report_no_movement,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")
os.makedirs(BASE_DIR, exist_ok=True)

# ==============================
# Helpers
# ==============================

def normalize_symbol(s):
    return s if s.endswith(".IS") else f"{s}.IS"

_TV_CACHE = {}
_TV_CACHE_TTL = 60

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


def yf_download_safe(ticker, period, interval):
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        return df.dropna(how="all")
    except Exception:
        return None


def fetch_timeframe_indicators(df, symbol=None):
    if df is None or df.empty or len(df) < 20:
        return None

    close = df["Close"].copy()

    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live:
            close.iloc[-1] = live

    rsi_series = calculate_rsi(close)
    ema_series = {k: calculate_ema(close, k) for k in [20, 50, 100, 200]}

    s_break, r_break = detect_support_resistance_break(df)

    out = {
        "last_close": float(close.iloc[-1]),
        "last_open": float(df["Open"].iloc[-1]),
        "ema20": float(ema_series[20].iloc[-1]),
        "ema50": float(ema_series[50].iloc[-1]),
        "ema100": float(ema_series[100].iloc[-1]),
        "ema200": float(ema_series[200].iloc[-1]),
        "rsi": float(rsi_series.iloc[-1]),
        "support_break": s_break,
        "resistance_break": r_break,
    }

    try:
        vol = int(df["Volume"].iloc[-1])
        vol_avg = int(df["Volume"].rolling(20).mean().iloc[-1])
        out["volume"] = vol
        out["volume_ok"] = vol > vol_avg
    except Exception:
        pass

    return out


# ==============================
# Core
# ==============================

def fetch_one_symbol(symbol_raw):
    symbol = normalize_symbol(symbol_raw)

    df_15m = yf_download_safe(symbol, "7d", "15m")
    used_tf = "15m"

    if df_15m is None:
        df_15m = yf_download_safe(symbol, "14d", "30m")
        used_tf = "30m"

    if df_15m is None:
        report_no_data(symbol_raw)
        return None

    tf_main = fetch_timeframe_indicators(df_15m, symbol)
    if tf_main is None:
        report_no_movement(symbol_raw)
        return None

    report_success(symbol_raw)

    df_5m = yf_download_safe(symbol, "3d", "5m")
    df_1h = yf_download_safe(symbol, "14d", "60m")
    df_4h = yf_download_safe(symbol, "60d", "4h")
    df_1d = yf_download_safe(symbol, "120d", "1d")

    ns, nr = nearest_support_resistance_from_history(df_15m)

    return {
        "symbol": symbol_raw,
        "current_price": tf_main["last_close"],
        "three_peak_break": detect_three_peaks(df_15m["Close"]),
        "support_break": tf_main["support_break"],
        "resistance_break": tf_main["resistance_break"],
        "nearest_support": ns,
        "nearest_resistance": nr,
        "used_timeframe": used_tf,
        "tf": {
            "5m": fetch_timeframe_indicators(df_5m, symbol) if df_5m is not None else None,
            used_tf: tf_main,
            "1h": fetch_timeframe_indicators(df_1h, symbol) if df_1h is not None else None,
            "4h": fetch_timeframe_indicators(df_4h, symbol) if df_4h is not None else None,
            "1d": fetch_timeframe_indicators(df_1d, symbol) if df_1d is not None else None,
        }
    }


def fetch_bist_data():
    out = []
    symbols = get_active_symbols()

    for s in symbols:
        try:
            r = fetch_one_symbol(s)
            if r:
                out.append(r)
        except Exception:
            continue
        time.sleep(0.15)

    return out
