import time
import json
import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

from utils import (
    FALLBACK_SYMBOLS,
    calculate_rsi,
    detect_three_peaks,
    detect_support_resistance_break,
    nearest_support_resistance_from_history,
)

# ==================================================
# STATE
# ==================================================
STATE_DIR = "data"
STATE_FILE = os.path.join(STATE_DIR, "fallback_state.json")
os.makedirs(STATE_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

STATE = load_state()

# ==================================================
# TRADINGVIEW LIVE PRICE
# ==================================================
_TV_CACHE = {}
_TV_TTL = 60

def tv_live_price(symbol):
    now = time.time()
    c = _TV_CACHE.get(symbol)
    if c and now - c["ts"] < _TV_TTL:
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
def ema(series, p):
    return series.ewm(span=p, adjust=False).mean()

# ==================================================
# SAFE YF
# ==================================================
def yf_safe(ticker, period, interval):
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
# FALLBACK SYMBOLS
# ==================================================
def get_bist_symbols():
    return FALLBACK_SYMBOLS.copy()

# ==================================================
# INDICATORS
# ==================================================
def tf_indicators(df, symbol=None):
    if df is None or df.empty:
        return None

    close = df["Close"].copy()

    if symbol:
        live = tv_live_price(symbol.replace(".IS", ""))
        if live:
            close.iloc[-1] = live

    rsi = calculate_rsi(close)
    if rsi.isna().all():
        return None

    out = {
        "close": float(close.iloc[-1]),
        "open": float(df["Open"].iloc[-1]),
        "green": close.iloc[-1] > df["Open"].iloc[-1],
        "ema20": float(ema(close, 20).iloc[-1]),
        "ema50": float(ema(close, 50).iloc[-1]),
        "ema100": float(ema(close, 100).iloc[-1]),
        "ema200": float(ema(close, 200).iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
    }

    try:
        out["volume"] = int(df["Volume"].iloc[-1])
        out["volume_avg"] = int(df["Volume"].iloc[-6:-1].mean())
        out["volume_ok"] = out["volume"] > out["volume_avg"]
    except Exception:
        pass

    s_break, r_break = detect_support_resistance_break(df)
    out["support_break"] = s_break
    out["resistance_break"] = r_break

    return out

# ==================================================
# FETCH ONE SYMBOL (15m → 30m)
# ==================================================
def fetch_one_symbol(sym):
    df = yf_safe(sym, "7d", "15m")
    used_tf = "15m"

    if df is None:
        df = yf_safe(sym, "14d", "30m")
        used_tf = "30m"

    if df is None:
        return None

    tf_main = tf_indicators(df, sym)
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
        tf_main["support_break"]
        or tf_main["resistance_break"]
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

    df_1h = yf_safe(sym, "14d", "60m")
    df_4h = yf_safe(sym, "60d", "4h")
    df_1d = yf_safe(sym, "120d", "1d")

    ns, nr = nearest_support_resistance_from_history(df)

    return {
        "symbol": symbol,
        "price": tf_main["close"],
        "used_tf": used_tf,
        "three_peak_break": detect_three_peaks(df["Close"]),
        "nearest_support": ns,
        "nearest_resistance": nr,
        "tf": {
            used_tf: tf_main,
            "1h": tf_indicators(df_1h),
            "4h": tf_indicators(df_4h),
            "1d": tf_indicators(df_1d)
        }
    }

# ==================================================
# FETCH ALL
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
