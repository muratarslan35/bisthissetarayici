import time
import os
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

from utils import (
    FALLBACK_SYMBOLS,
    calculate_rsi,
    calculate_ema,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
    to_tr_timezone
)

import fallback_manager   # 🔴 YENİ – PASİF / AKTİF YÖNETİCİ

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")
os.makedirs(BASE_DIR, exist_ok=True)

# ---------------------------------------------------
# TradingView canlı fiyat cache
# ---------------------------------------------------
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


# ---------------------------------------------------
# yfinance güvenli veri çekme
# ---------------------------------------------------
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


# ---------------------------------------------------
# Incremental RSI / EMA
# ---------------------------------------------------
def incremental_indicators(prev_close_series, prev_rsi_series, prev_ema_series, new_close):
    close_series = prev_close_series.append(
        pd.Series([new_close]), ignore_index=True
    )
    rsi_series = calculate_rsi(close_series)
    ema_series = {k: calculate_ema(close_series, k) for k in [20, 50, 100, 200]}
    return close_series, rsi_series, ema_series


# ---------------------------------------------------
# Timeframe indikatörleri
# ---------------------------------------------------
def fetch_timeframe_indicators(df, symbol=None, prev=None):
    if df is None or df.empty or len(df) < 20:
        return None

    close = df["Close"].copy()

    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live:
            close.iloc[-1] = live

    if prev:
        close, rsi_series, ema_series = incremental_indicators(
            prev["close"],
            prev["rsi_series"],
            prev["ema_series"],
            close.iloc[-1]
        )
    else:
        rsi_series = calculate_rsi(close)
        ema_series = {k: calculate_ema(close, k) for k in [20, 50, 100, 200]}

    out = {
        "df": df,
        "last_close": float(close.iloc[-1]),
        "last_open": float(df["Open"].iloc[-1]),
        "ema20": float(ema_series[20].iloc[-1]),
        "ema50": float(ema_series[50].iloc[-1]),
        "ema100": float(ema_series[100].iloc[-1]),
        "ema200": float(ema_series[200].iloc[-1]),
        "rsi": float(rsi_series.iloc[-1]),
        "close": close,
        "rsi_series": rsi_series,
        "ema_series": ema_series
    }

    try:
        out["volume"] = int(df["Volume"].iloc[-1])
        out["volume_avg_20"] = int(df["Volume"].rolling(20).mean().iloc[-1])
        out["volume_ok"] = out["volume"] > out["volume_avg_20"]
    except Exception:
        pass

    s_break, r_break = detect_support_resistance_break(df)
    out["support_break"] = s_break
    out["resistance_break"] = r_break

    return out


# ---------------------------------------------------
# Incremental cache
# ---------------------------------------------------
_prev_1h = {}
_prev_4h = {}


# ---------------------------------------------------
# TEK HİSSE ANALİZİ
# ---------------------------------------------------
def fetch_one_symbol(sym):
    fallback_manager.ensure_symbol(sym)

    df_15m = yf_download_safe(sym, "7d", "15m")
    used_tf = "15m"

    if df_15m is None:
        df_15m = yf_download_safe(sym, "14d", "30m")
        used_tf = "30m"

    if df_15m is None:
        fallback_manager.report_no_data(sym)
        return None

    tf_main = fetch_timeframe_indicators(df_15m, sym)
    if tf_main is None:
        fallback_manager.report_no_movement(sym)
        return None

    active = (
        tf_main["resistance_break"]
        or tf_main["support_break"]
        or tf_main["rsi"] < 30
        or tf_main["rsi"] > 70
    )

    if active:
        fallback_manager.report_success(sym)
    else:
        fallback_manager.report_no_movement(sym)

    symbol = sym.replace(".IS", "")

    df_5m = yf_download_safe(sym, "3d", "5m")
    df_1h = yf_download_safe(sym, "14d", "60m")
    df_4h = yf_download_safe(sym, "60d", "4h")
    df_1d = yf_download_safe(sym, "120d", "1d")

    prev_1h = _prev_1h.get(symbol)
    prev_4h = _prev_4h.get(symbol)

    tf_1h = fetch_timeframe_indicators(df_1h, sym, prev_1h)
    tf_4h = fetch_timeframe_indicators(df_4h, sym, prev_4h)

    if tf_1h:
        _prev_1h[symbol] = {
            "close": tf_1h["close"],
            "rsi_series": tf_1h["rsi_series"],
            "ema_series": tf_1h["ema_series"]
        }

    if tf_4h:
        _prev_4h[symbol] = {
            "close": tf_4h["close"],
            "rsi_series": tf_4h["rsi_series"],
            "ema_series": tf_4h["ema_series"]
        }

    ns, nr = nearest_support_resistance_from_history(df_15m)

    return {
        "symbol": symbol,
        "current_price": tf_main["last_close"],
        "three_peak_break": detect_three_peaks(df_15m["Close"]),
        "support_break": tf_main["support_break"],
        "resistance_break": tf_main["resistance_break"],
        "nearest_support": ns,
        "nearest_resistance": nr,
        "used_timeframe": used_tf,
        "tf": {
            "5m": fetch_timeframe_indicators(df_5m, sym) if df_5m is not None else None,
            used_tf: tf_main,
            "1h": tf_1h if tf_1h else {},
            "4h": tf_4h if tf_4h else {},
            "1d": fetch_timeframe_indicators(df_1d, sym) if df_1d is not None else None
        }
    }


# ---------------------------------------------------
# BIST TARAYICI (fallback entegre)
# ---------------------------------------------------
def fetch_bist_data():
    out = []

    active_symbols = fallback_manager.get_active_symbols()
    if not active_symbols:
        active_symbols = FALLBACK_SYMBOLS

    for s in active_symbols:
        try:
            r = fetch_one_symbol(s)
            if r:
                out.append(r)
        except Exception:
            fallback_manager.report_no_data(s)
        time.sleep(0.15)

    return out
