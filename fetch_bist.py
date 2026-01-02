import time
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd
import requests

from utils import (
    resolve_symbols,
    fetch_tradingview_price,
    FALLBACK_SYMBOLS
)

MAX_LOOKBACK = {
    "15m": "5d",
    "30m": "5d",
    "1h": "10d",
    "1d": "6mo"
}

# ======================================================
# INDICATORS
# ======================================================

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

# ======================================================
# RESAMPLE
# ======================================================

def resample_df(df, rule):
    return (
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

# ======================================================
# YFINANCE FETCH
# ======================================================

def fetch_yf(symbol, interval):
    try:
        if not symbol.upper().endswith(".IS"):
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
            print(f"⚠ YF boş veri → {symbol} [{interval}]")
            return None

        df = df.rename_axis("Datetime").reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df.set_index("Datetime", inplace=True)
        return df

    except Exception as e:
        print(f"❌ YF hata → {symbol} [{interval}] | {e}")
        return None

# ======================================================
# TIMEFRAME BUILD
# ======================================================

def build_tf_data(symbol):
    base_df = fetch_yf(symbol, "15m") or fetch_yf(symbol, "30m")
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

    for key, rule in [("1h", "1H"), ("4h", "4H")]:
        d = resample_df(base_df, rule)
        if d.empty:
            print(f"⚠ Resample boş → {symbol} [{key}]")
            return None

        d["ema20"] = compute_ema(d["Close"], 20)
        d["ema50"] = compute_ema(d["Close"], 50)

        tf[key] = {
            "ema20": float(d["ema20"].iloc[-1]),
            "ema50": float(d["ema50"].iloc[-1]),
            "df": d
        }

    return tf

# ======================================================
# MAIN FETCH (LOG'LU)
# ======================================================

def fetch_bist_data(symbol_data=None):
    results = []
    tried = set()

    symbols = resolve_symbols(symbol_data)
    all_symbols = symbols + FALLBACK_SYMBOLS

    print(f"\n🔍 TARAMA BAŞLADI | TOPLAM SEMBOL: {len(all_symbols)}")

    for symbol in all_symbols:
        if symbol in tried:
            continue
        tried.add(symbol)

        print(f"➡ Taranıyor: {symbol}")

        price = fetch_tradingview_price(symbol)
        if not price:
            print(f"⚠ TV fiyat yok → {symbol}")
            continue

        tf = build_tf_data(symbol)
        if not tf:
            print(f"⚠ TF eksik → {symbol}")
            continue

        results.append({
            "symbol": symbol,
            "current_price": price,
            "tf": tf,
            "fetched_at": datetime.now(timezone.utc)
        })

        print(f"✅ OK → {symbol}")
        time.sleep(0.12)

    print(f"✅ TARAMA BİTTİ | GEÇERLİ HİSSE: {len(results)}\n")
    return results
