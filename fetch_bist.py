import time
import os
import requests
import pandas as pd
import yfinance as yf

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

# ==============================
# PATH
# ==============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==============================
# SYMBOL
# ==============================
def normalize_symbol(symbol: str) -> str:
    return symbol if symbol.endswith(".IS") else f"{symbol}.IS"

# ==============================
# TRADINGVIEW LIVE PRICE (CACHE)
# ==============================
_TV_CACHE = {}
_TV_CACHE_TTL = 60  # saniye

def tv_live_price(symbol: str):
    now = time.time()
    cache = _TV_CACHE.get(symbol)

    if cache and now - cache["ts"] < _TV_CACHE_TTL:
        return cache["price"]

    try:
        r = requests.get(
            "https://scanner.tradingview.com/symbol",
            params={"symbol": f"BIST:{symbol}"},
            timeout=4
        )
        js = r.json()
        price = js.get("price")
        if isinstance(price, (int, float)):
            _TV_CACHE[symbol] = {"price": float(price), "ts": now}
            return float(price)
    except Exception:
        pass

    return None

# ==============================
# YFINANCE SAFE DOWNLOAD
# ==============================
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

# ==============================
# INDICATORS
# ==============================
def fetch_timeframe_indicators(df, symbol=None):
    if df is None or df.empty or len(df) < 20:
        return None

    close = df["Close"].copy()

    # canlı fiyat override
    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if isinstance(live, (int, float)):
            close.iloc[-1] = live

    rsi = calculate_rsi(close)
    ema20 = calculate_ema(close, 20)
    ema50 = calculate_ema(close, 50)
    ema100 = calculate_ema(close, 100)
    ema200 = calculate_ema(close, 200)

    s_break, r_break = detect_support_resistance_break(df)

    out = {
        "open": float(df["Open"].iloc[-1]),
        "close": float(close.iloc[-1]),
        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "ema100": float(ema100.iloc[-1]),
        "ema200": float(ema200.iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
        "support_break": bool(s_break),
        "resistance_break": bool(r_break),
    }

    try:
        vol = float(df["Volume"].iloc[-1])
        vol_avg = float(df["Volume"].rolling(20).mean().iloc[-1])
        out["volume"] = vol
        out["volume_avg_20"] = vol_avg
    except Exception:
        pass

    return out

# ==============================
# FETCH ONE SYMBOL
# ==============================
def fetch_one_symbol(symbol_raw):
    symbol = normalize_symbol(symbol_raw)

    # ana timeframe
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

    # diğer timeframe’ler
    df_5m = yf_download_safe(symbol, "3d", "5m")
    df_1h = yf_download_safe(symbol, "14d", "60m")
    df_4h = yf_download_safe(symbol, "60d", "4h")
    df_1d = yf_download_safe(symbol, "120d", "1d")

    nearest_support, nearest_resistance = nearest_support_resistance_from_history(df_15m)

    return {
        "symbol": symbol_raw,
        "current_price": tf_main["close"],
        "three_peak_break": detect_three_peaks(df_15m["Close"]),
        "support_break": tf_main["support_break"],
        "resistance_break": tf_main["resistance_break"],
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "used_timeframe": used_tf,
        "tf": {
            "5m": fetch_timeframe_indicators(df_5m, symbol) if df_5m is not None else None,
            used_tf: tf_main,
            "1h": fetch_timeframe_indicators(df_1h, symbol) if df_1h is not None else None,
            "4h": fetch_timeframe_indicators(df_4h, symbol) if df_4h is not None else None,
            "1d": fetch_timeframe_indicators(df_1d, symbol) if df_1d is not None else None,
        }
    }

# ==============================
# FETCH ALL BIST
# ==============================
def fetch_bist_data():
    results = []
    symbols = get_active_symbols()

    for sym in symbols:
        try:
            data = fetch_one_symbol(sym)
            if data:
                results.append(data)
        except Exception:
            continue

        time.sleep(0.15)  # rate limit

    return results
