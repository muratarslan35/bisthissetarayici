import time
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

from utils import (
    resolve_symbols,
    fetch_tradingview_price,
    FALLBACK_SYMBOLS
)

MAX_LOOKBACK = {
    "15m": "5d",
    "30m": "5d",
}

# =========================
# INDICATORS
# =========================

def compute_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# =========================
# RESAMPLE (SAFE)
# =========================

def resample_df(df, rule):
    if df is None or df.empty:
        return None

    d = (
        df.resample(rule)
        .agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })
        .dropna()
    )

    return d if not d.empty else None

# =========================
# YFINANCE FETCH (SAFE)
# =========================

def fetch_yf(symbol, interval):
    try:
        if not symbol.endswith(".IS"):
            symbol = f"{symbol}.IS"

        df = yf.download(
            symbol,
            interval=interval,
            period=MAX_LOOKBACK.get(interval, "5d"),
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if df.empty:
            return None

        df = df.rename_axis("Datetime").reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df.set_index("Datetime", inplace=True)
        return df

    except Exception:
        return None

# =========================
# TF BUILD (BOOLEAN BUG FIXED)
# =========================

def build_tf_data(symbol):
    base_df = fetch_yf(symbol, "15m")
    if base_df is None:
        base_df = fetch_yf(symbol, "30m")

    if base_df is None:
        return None

    base_df["ema20"] = compute_ema(base_df["Close"], 20)
    base_df["ema50"] = compute_ema(base_df["Close"], 50)
    base_df["ema200"] = compute_ema(base_df["Close"], 200)
    base_df["rsi"] = compute_rsi(base_df["Close"])

    base_df["volume_ma"] = base_df["Volume"].rolling(20).mean()
    base_df["volume_ok"] = base_df["Volume"] > base_df["volume_ma"] * 1.5

    tf = {
        "15m": {
            "ema20": float(base_df["ema20"].iloc[-1]),
            "ema50": float(base_df["ema50"].iloc[-1]),
            "ema200": float(base_df["ema200"].iloc[-1]),
            "rsi": float(base_df["rsi"].iloc[-1]),
            "volume_ok": bool(base_df["volume_ok"].iloc[-1]),
            "df": base_df
        }
    }

    d1h = resample_df(base_df, "1H")
    if d1h is not None:
        d1h["ema20"] = compute_ema(d1h["Close"], 20)
        d1h["ema50"] = compute_ema(d1h["Close"], 50)
        tf["1h"] = {
            "ema20": float(d1h["ema20"].iloc[-1]),
            "ema50": float(d1h["ema50"].iloc[-1]),
            "df": d1h
        }

    d4h = resample_df(base_df, "4H")
    if d4h is not None:
        d4h["ema20"] = compute_ema(d4h["Close"], 20)
        d4h["ema50"] = compute_ema(d4h["Close"], 50)
        tf["4h"] = {
            "ema20": float(d4h["ema20"].iloc[-1]),
            "ema50": float(d4h["ema50"].iloc[-1]),
            "df": d4h
        }

    return tf

# =========================
# MAIN FETCH (LOG’LU & KESİNTİSİZ)
# =========================

def fetch_bist_data(symbol_data=None):
    results = []
    tried = set()

    symbols = resolve_symbols(symbol_data)
    all_symbols = symbols + FALLBACK_SYMBOLS

    print(f"\n🔍 TARAMA BAŞLADI | TOPLAM: {len(all_symbols)}")

    for symbol in all_symbols:
        if symbol in tried:
            continue
        tried.add(symbol)

        print(f"➡ {symbol}")

        price = fetch_tradingview_price(symbol)
        if not price:
            print("⚠ TV fiyat yok")
            continue

        tf = build_tf_data(symbol)
        if not tf:
            print("⚠ TF yok")
            continue

        results.append({
            "symbol": symbol,
            "current_price": price,
            "tf": tf,
            "fetched_at": datetime.now(timezone.utc)
        })

        print("✅ OK")
        time.sleep(0.12)

    print(f"✅ TARAMA BİTTİ | GEÇERLİ: {len(results)}\n")
    return results
