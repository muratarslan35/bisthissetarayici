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
# SAFE COLUMN EXTRACTORS (KRİTİK)
# ======================================================

def col_series(df, name):
    """
    Close / Volume gibi kolonları her koşulda 1D Series yapar
    """
    if name not in df.columns:
        return None

    col = df[name]

    if isinstance(col, pd.DataFrame):
        return col.iloc[:, 0]

    return col

# ======================================================
# INDICATORS (1D SAFE)
# ======================================================

def compute_ema(series, period):
    series = series.astype(float)
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series, period=14):
    series = series.astype(float)

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ======================================================
# RESAMPLE (SAFE & FUTUREPROOF)
# ======================================================

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

# ======================================================
# YFINANCE FETCH
# ======================================================

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
            print(f"⚠ YF boş → {symbol} [{interval}]", flush=True)
            return None

        df = df.rename_axis("Datetime").reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df.set_index("Datetime", inplace=True)

        return df

    except Exception as e:
        print(f"❌ YF hata → {symbol} [{interval}] | {e}", flush=True)
        return None

# ======================================================
# TF BUILD (TAM GÜVENLİ)
# ======================================================

def build_tf_data(symbol):
    base_df = fetch_yf(symbol, "15m") or fetch_yf(symbol, "30m")
    if base_df is None or base_df.empty:
        return None

    close = col_series(base_df, "Close")
    volume = col_series(base_df, "Volume")

    if close is None or volume is None:
        return None

    base_df["ema20"] = compute_ema(close, 20)
    base_df["ema50"] = compute_ema(close, 50)
    base_df["ema200"] = compute_ema(close, 200)
    base_df["rsi"] = compute_rsi(close)

    base_df["volume_ma"] = volume.rolling(20).mean()
    base_df["volume_ok"] = volume.values > (base_df["volume_ma"].values * 1.5)

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

    # ---- 1H ----
    d1h = resample_df(base_df, "1h")
    if d1h is not None:
        c = col_series(d1h, "Close")
        if c is not None:
            d1h["ema20"] = compute_ema(c, 20)
            d1h["ema50"] = compute_ema(c, 50)
            tf["1h"] = {
                "ema20": float(d1h["ema20"].iloc[-1]),
                "ema50": float(d1h["ema50"].iloc[-1]),
                "df": d1h
            }

    # ---- 4H ----
    d4h = resample_df(base_df, "4h")
    if d4h is not None:
        c = col_series(d4h, "Close")
        if c is not None:
            d4h["ema20"] = compute_ema(c, 20)
            d4h["ema50"] = compute_ema(c, 50)
            tf["4h"] = {
                "ema20": float(d4h["ema20"].iloc[-1]),
                "ema50": float(d4h["ema50"].iloc[-1]),
                "df": d4h
            }

    return tf

# ======================================================
# MAIN FETCH (NOHUP UYUMLU)
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

    print(f"✅ TARAMA BİTTİ | GEÇERLİ: {len(results)}\n", flush=True)
    return results
