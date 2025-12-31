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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")
os.makedirs(BASE_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

STATE = load_state()

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
        if price is not None:
            price = float(price)
            _TV_CACHE[symbol] = {"price": price, "ts": now}
            return price
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
            progress=False
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

    df = df.copy()
    close = df["Close"].copy()

    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live is not None:
            close.iloc[-1] = live
            df.loc[df.index[-1], "Close"] = live

    rsi = calculate_rsi(close)

    out = {
        "df": df,
        "last_close": float(close.iloc[-1]),
        "last_open": float(df["Open"].iloc[-1]),
        "ema20": float(calculate_ema(close, 20).iloc[-1]),
        "ema50": float(calculate_ema(close, 50).iloc[-1]),
        "ema100": float(calculate_ema(close, 100).iloc[-1]),
        "ema200": float(calculate_ema(close, 200).iloc[-1]),
        "rsi": float(rsi.iloc[-1])
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

def fetch_one_symbol(sym):
    df_15m = yf_download_safe(sym, "7d", "15m")
    used_tf = "15m"

    if df_15m is None:
        df_15m = yf_download_safe(sym, "14d", "30m")
        used_tf = "30m"

    if df_15m is None:
        df_15m = yf_download_safe(sym, "14d", "60m")
        used_tf = "1h"

    if df_15m is None:
        return None

    tf_main = fetch_timeframe_indicators(df_15m, sym)
    if tf_main is None:
        return None

    symbol = sym.replace(".IS", "")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    s = STATE.setdefault(symbol, {
        "inactive_days": 0,
        "active_days": 0,
        "last_day": today
    })

    active = (
        tf_main["resistance_break"]
        or tf_main["support_break"]
        or tf_main["rsi"] < 30
        or tf_main["rsi"] > 70
    )

    if s["last_day"] != today:
        if active:
            s["active_days"] += 1
            s["inactive_days"] = 0
        else:
            s["inactive_days"] += 1
        s["last_day"] = today

    STATE[symbol] = s
    save_state(STATE)

    df_5m = yf_download_safe(sym, "3d", "5m")
    df_1h = yf_download_safe(sym, "14d", "60m")
    df_4h = yf_download_safe(sym, "60d", "4h")
    df_1d = yf_download_safe(sym, "120d", "1d")

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
            "1h": fetch_timeframe_indicators(df_1h, sym) if df_1h is not None else None,
            "4h": fetch_timeframe_indicators(df_4h, sym) if df_4h is not None else None,
            "1d": fetch_timeframe_indicators(df_1d, sym) if df_1d is not None else None
        }
    }

def fetch_bist_data():
    out = []
    for s in FALLBACK_SYMBOLS:
        try:
            r = fetch_one_symbol(s)
            if r is not None:
                out.append(r)
        except Exception:
            pass
        time.sleep(0.15)
    return out
