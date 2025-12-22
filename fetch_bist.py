import time
import requests
import pandas as pd
import yfinance as yf

from utils import (
    FALLBACK_SYMBOLS,
    calculate_rsi,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
)

# ==================================================
# TRADINGVIEW PSEUDO LIVE PRICE (CACHE)
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
# SAFE YFINANCE (SESSİZ)
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
# SYMBOL LIST — SADECE FALLBACK
# ==================================================
def get_bist_symbols():
    # 🔥 YF uyumlu, stabil, kontrollü liste
    return FALLBACK_SYMBOLS.copy()


# ==================================================
# TF INDICATORS (15M PSEUDO LIVE)
# ==================================================
def fetch_timeframe_indicators(df, symbol=None):
    if df is None or df.empty:
        return None

    close = df["Close"].copy()

    # pseudo-live sadece son mum
    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live:
            close.iloc[-1] = live

    ema20 = calculate_ema(close, 20)
    ema50 = calculate_ema(close, 50)
    rsi = calculate_rsi(close)

    if rsi.isna().all():
        return None

    out = {
        "last_close": float(close.iloc[-1]),
        "last_open": float(df["Open"].iloc[-1]),
        "last_green": close.iloc[-1] > df["Open"].iloc[-1],
        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
    }

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
# FETCH ONE SYMBOL (SİNYAL GARANTİLİ)
# ==================================================
def fetch_one_symbol(sym):
    df_15 = yf_download_safe(sym, "7d", "15m")
    if df_15 is None:
        return None

    tf15 = fetch_timeframe_indicators(df_15, sym)
    if tf15 is None:
        return None

    df_1h = yf_download_safe(sym, "14d", "60m")
    df_4h = yf_download_safe(sym, "60d", "4h")
    df_1d = yf_download_safe(sym, "120d", "1d")

    tf1h = fetch_timeframe_indicators(df_1h)
    tf4h = fetch_timeframe_indicators(df_4h)
    tf1d = fetch_timeframe_indicators(df_1d)

    ns, nr = nearest_support_resistance_from_history(df_15)
    three_peak = detect_three_peaks(df_15["Close"])

    return {
        "symbol": sym.replace(".IS", ""),
        "current_price": tf15.get("last_close"),
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
# FETCH ALL (HIZLI + STABİL)
# ==================================================
def fetch_bist_data():
    out = []
    for s in get_bist_symbols():
        try:
            r = fetch_one_symbol(s)
            if r:
                out.append(r)
        except Exception:
            pass
        time.sleep(0.15)
    return out
