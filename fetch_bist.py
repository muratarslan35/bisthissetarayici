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

# ======================================================
# INDICATORS (SERIES SAFE)
# ======================================================

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ======================================================
# RESAMPLE (BOOLEAN SAFE)
# ======================================================

def resample_df(df: pd.DataFrame, rule: str):
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

    if d.empty:
        return None

    return d

# ======================================================
# YFINANCE FETCH (NET)
# ======================================================

def fetch_yf(symbol: str, interval: str):
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

        if df is None or df.empty:
            return None

        df = df.rename_axis("Datetime").reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df.set_index("Datetime", inplace=True)

        return df

    except Exception as e:
        print(f"❌ YF hata → {symbol} [{interval}] | {e}", flush=True)
        return None

# ======================================================
# TIMEFRAME BUILD (NO AMBIGUITY)
# ======================================================

def build_tf_data(symbol: str):
    base_df = fetch_yf(symbol, "15m")

    if base_df is None:
        base_df = fetch_yf(symbol, "30m")

    if base_df is None or base_df.empty:
        return None

    close = base_df["Close"]
    volume = base_df["Volume"]

    base_df["ema20"] = compute_ema(close, 20)
    base_df["ema50"] = compute_ema(close, 50)
    base_df["ema200"] = compute_ema(close, 200)
    base_df["rsi"] = compute_rsi(close)

    volume_ma = volume.rolling(20).mean()

    # 🔥 ALIGNMENT SAFE
    base_df["volume_ok"] = volume.values > (volume_ma.values * 1.5)

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

    d1h = resample_df(base_df, "1h")
    if d1h is not None:
        d1h["ema20"] = compute_ema(d1h["Close"], 20)
        d1h["ema50"] = compute_ema(d1h["Close"], 50)

        tf["1h"] = {
            "ema20": float(d1h["ema20"].iloc[-1]),
            "ema50": float(d1h["ema50"].iloc[-1]),
            "df": d1h
        }

    d4h = resample_df(base_df, "4h")
    if d4h is not None:
        d4h["ema20"] = compute_ema(d4h["Close"], 20)
        d4h["ema50"] = compute_ema(d4h["Close"], 50)

        tf["4h"] = {
            "ema20": float(d4h["ema20"].iloc[-1]),
            "ema50": float(d4h["ema50"].iloc[-1]),
            "df": d4h
        }

    return tf

# ======================================================
# MAIN FETCH (LOG + SAFE)
# ======================================================

def fetch_bist_data(symbol_data=None):
    results = []
    tried = set()

    symbols = resolve_symbols(symbol_data)
    all_symbols = symbols + FALLBACK_SYMBOLS

    print(f"\n🔍 TARAMA BAŞLADI | TOPLAM: {len(all_symbols)}", flush=True)

    for symbol in all_symbols:
        if symbol in tried:
            continue
        tried.add(symbol)

        print(f"➡ {symbol}", flush=True)

        try:
            price = fetch_tradingview_price(symbol)
            if not price:
                print("⚠ TV fiyat yok", flush=True)
                continue

            tf = build_tf_data(symbol)
            if tf is None:
                print("⚠ TF yok", flush=True)
                continue

            results.append({
                "symbol": symbol,
                "current_price": price,
                "tf": tf,
                "fetched_at": datetime.now(timezone.utc)
            })

            print("✅ OK", flush=True)
            time.sleep(0.12)

        except Exception as e:
            print(f"🔥 fetch_bist_data hata → {symbol} | {e}", flush=True)
            continue

    print(f"✅ TARAMA BİTTİ | GEÇERLİ: {len(results)}\n", flush=True)
    return results
