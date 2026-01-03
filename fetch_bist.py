import time
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

from utils import (
    resolve_symbols,
    fetch_tradingview_price,
    FALLBACK_SYMBOLS
)

# ======================================================
# YFINANCE LOOKBACK (BIST SAFE)
# ======================================================
MAX_LOOKBACK = {
    "15m": "5d",
    "30m": "5d",
    "1d": "6mo"
}

# ======================================================
# INDICATORS
# ======================================================
def compute_ema(series, period):
    series = pd.Series(series).astype(float)
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series, period=14):
    series = pd.Series(series).astype(float)
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
    if df is None or df.empty:
        return None
    try:
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
    except Exception:
        return None

# ======================================================
# YFINANCE FETCH (SAFE)
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

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        df = df.reset_index()
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        df = df.set_index("Datetime")

        return df

    except Exception as e:
        print(f"❌ YF hata → {symbol} [{interval}] | {e}", flush=True)
        return None

# ======================================================
# BUILD TIMEFRAMES (LIVE EMA + 1D)
# ======================================================
def build_tf_data(symbol, live_price=None):
    base_df = fetch_yf(symbol, "15m")
    if base_df is None:
        base_df = fetch_yf(symbol, "30m")
    if base_df is None or base_df.empty:
        return None

    close = pd.Series(base_df["Close"]).astype(float)
    volume = pd.Series(base_df["Volume"]).astype(float)

    # 15m NORMAL
    base_df["ema20"] = compute_ema(close, 20)
    base_df["ema50"] = compute_ema(close, 50)
    base_df["ema200"] = compute_ema(close, 200)
    base_df["rsi"] = compute_rsi(close)

    vol_ma = volume.rolling(20).mean()
    base_df["volume_ok"] = volume > (vol_ma * 1.5)

    # 🔥 LIVE EMA (HAYALİ 15M MUM)
    ema20_live = ema50_live = ema200_live = None
    if live_price is not None:
        hybrid_close = close.tolist() + [float(live_price)]
        ema20_live = float(compute_ema(hybrid_close, 20).iloc[-1])
        ema50_live = float(compute_ema(hybrid_close, 50).iloc[-1])
        ema200_live = float(compute_ema(hybrid_close, 200).iloc[-1])

    tf = {
        "15m": {
            "ema20": float(base_df["ema20"].iloc[-1]),
            "ema50": float(base_df["ema50"].iloc[-1]),
            "ema200": float(base_df["ema200"].iloc[-1]),
            "ema20_live": ema20_live,
            "ema50_live": ema50_live,
            "ema200_live": ema200_live,
            "rsi": float(base_df["rsi"].iloc[-1]),
            "volume_ok": bool(base_df["volume_ok"].iloc[-1]),
            "df": base_df
        }
    }

    # 1H
    d1h = resample_df(base_df, "1h")
    if d1h is not None:
        c1 = pd.Series(d1h["Close"]).astype(float)
        d1h["ema20"] = compute_ema(c1, 20)
        d1h["ema50"] = compute_ema(c1, 50)
        d1h["rsi"] = compute_rsi(c1)
        tf["1h"] = {
            "ema20": float(d1h["ema20"].iloc[-1]),
            "ema50": float(d1h["ema50"].iloc[-1]),
            "rsi": float(d1h["rsi"].iloc[-1]),
            "df": d1h
        }

    # 4H
    d4h = resample_df(base_df, "4h")
    if d4h is not None:
        c4 = pd.Series(d4h["Close"]).astype(float)
        d4h["ema20"] = compute_ema(c4, 20)
        d4h["ema50"] = compute_ema(c4, 50)
        d4h["rsi"] = compute_rsi(c4)
        tf["4h"] = {
            "ema20": float(d4h["ema20"].iloc[-1]),
            "ema50": float(d4h["ema50"].iloc[-1]),
            "rsi": float(d4h["rsi"].iloc[-1]),
            "df": d4h
        }

    # 1D (ZORUNLU)
    d1d = fetch_yf(symbol, "1d")
    if d1d is not None and len(d1d) >= 3:
        c1d = pd.Series(d1d["Close"]).astype(float)
        d1d["ema50"] = compute_ema(c1d, 50)
        d1d["ema200"] = compute_ema(c1d, 200)
        d1d["rsi"] = compute_rsi(c1d)
        tf["1d"] = {
            "ema50": float(d1d["ema50"].iloc[-1]),
            "ema200": float(d1d["ema200"].iloc[-1]),
            "rsi": float(d1d["rsi"].iloc[-1]),
            "df": d1d
        }

    return tf

# ======================================================
# MAIN FETCH
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

        try:
            print(f"➡ {symbol}", flush=True)

            price = fetch_tradingview_price(symbol)
            if price is None:
                print("⚠ TV fiyat yok", flush=True)
                continue

            tf = build_tf_data(symbol, live_price=price)
            if tf is None or "1d" not in tf:
                print("⚠ TF/1D eksik", flush=True)
                continue

            results.append({
                "symbol": symbol,
                "current_price": float(price),
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
