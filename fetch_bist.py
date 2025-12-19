# fetch_bist.py
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone

from utils import (
    FALLBACK_SYMBOLS,
    calculate_rsi,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
    to_tr_timezone,
)

yf.pdr_override = False


# ==================================================
# EMA HELPERS
# ==================================================
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


# ==================================================
# SAFE YFINANCE DOWNLOAD
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
            if ("Close", ticker) in df.columns:
                df = pd.DataFrame({
                    "Open": df[("Open", ticker)],
                    "High": df[("High", ticker)],
                    "Low": df[("Low", ticker)],
                    "Close": df[("Close", ticker)],
                    "Volume": df[("Volume", ticker)]
                })
            else:
                return None

        return df.dropna(how="all")

    except Exception:
        return None


# ==================================================
# BIST SYMBOL LIST
# ==================================================
def get_bist_symbols():
    try:
        url = "https://api.isyatirim.com.tr/index/indexsectorperformance"
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        js = r.json()

        syms = []
        for item in js:
            if item.get("indexCode") in ("XU030", "XU100"):
                for c in item.get("components", []):
                    s = c.get("symbol")
                    if s:
                        syms.append(s if s.endswith(".IS") else s + ".IS")

        syms = list(dict.fromkeys(syms))
        if syms:
            return syms

    except Exception as e:
        print("[fetch_bist] API fail → fallback", e)

    return FALLBACK_SYMBOLS.copy()


# ==================================================
# INDICATORS PER TIMEFRAME
# ==================================================
def fetch_timeframe_indicators(df):
    out = {}
    if df is None or df.empty:
        return out

    try:
        close = df["Close"]

        ema20 = calculate_ema(close, 20)
        ema50 = calculate_ema(close, 50)

        out["last_close"] = float(close.iloc[-1])
        out["last_open"] = float(df["Open"].iloc[-1])
        out["last_green"] = out["last_close"] > out["last_open"]

        out["ema20"] = float(ema20.iloc[-1])
        out["ema50"] = float(ema50.iloc[-1])

        out["above_ema20"] = out["last_close"] > out["ema20"]
        out["above_ema50"] = out["last_close"] > out["ema50"]

        out["rsi"] = float(calculate_rsi(close).iloc[-1])
    except Exception:
        pass

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
        raise ValueError("no 15m data")

    df_1h = yf_download_safe(sym, "14d", "60m")
    df_4h = yf_download_safe(sym, "60d", "240m")
    df_1d = yf_download_safe(sym, "120d", "1d")

    tf15 = fetch_timeframe_indicators(df_15)
    tf1h = fetch_timeframe_indicators(df_1h)
    tf4h = fetch_timeframe_indicators(df_4h)
    tf1d = fetch_timeframe_indicators(df_1d)

    price = tf15.get("last_close")
    rsi_15 = tf15.get("rsi")

    # ===============================================
    # NEAREST SUPPORT / RESISTANCE
    # ===============================================
    ns, nr = nearest_support_resistance_from_history(df_15)

    resistance_continuation = False
    if tf15.get("resistance_break") and nr:
        resistance_continuation = price > nr

    # ===============================================
    # THREE PEAK
    # ===============================================
    three_peak = detect_three_peaks(df_15["Close"])

    # ===============================================
    # SUPER COMBINED (AYNEN KORUNDU)
    # ===============================================
    super_ok = False
    try:
        if len(df_15) >= 20:
            if (
                tf15.get("last_green")
                and tf1h.get("last_green")
                and tf4h.get("last_green")
                and tf1d.get("last_green")
                and 45 <= rsi_15 <= 65
                and not three_peak
            ):
                super_ok = True
    except Exception:
        pass

    return {
        "symbol": sym.replace(".IS", ""),
        "current_price": price,
        "RSI": rsi_15,
        "volume": tf15.get("volume"),
        "three_peak_break": three_peak,

        # ---- SUPPORT / RESISTANCE ----
        "support_break": tf15.get("support_break"),
        "resistance_break": tf15.get("resistance_break"),
        "nearest_support": ns,
        "nearest_resistance": nr,
        "resistance_continuation": resistance_continuation,

        # ---- TIMEFRAMES ----
        "tf": {
            "15m": tf15,
            "1h": tf1h,
            "4h": tf4h,
            "1d": tf1d
        },

        # ---- SIGNALS ----
        "super_combined_ok": super_ok,
    }


# ==================================================
# MAIN FETCH
# ==================================================
def fetch_bist_data():
    symbols = get_bist_symbols()
    results = []

    for s in symbols:
        try:
            rec = fetch_one_symbol(s)
            if rec:
                results.append(rec)
        except Exception as e:
            print("[fetch_bist]", s, e)
            continue

        time.sleep(0.12)

    return results
