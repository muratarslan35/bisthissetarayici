import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

FALLBACK_SYMBOLS = [
    # ... (senin verdiğin tam liste aynen) ...
]

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).fillna(50)

def detect_support_resistance_break(df, lookback=20):
    prev_low = df["Low"].iloc[:-1].rolling(lookback, min_periods=1).min().iloc[-1]
    prev_high = df["High"].iloc[:-1].rolling(lookback, min_periods=1).max().iloc[-1]
    close = df["Close"].iloc[-1]
    return close < prev_low, close > prev_high

def nearest_support_resistance_from_history(df, lookback=100):
    highs = df["High"].rolling(3, center=True).max()
    lows = df["Low"].rolling(3, center=True).min()
    ph = df["High"][df["High"] == highs]
    pl = df["Low"][df["Low"] == lows]

    price = df["Close"].iloc[-1]

    resistances = [v for v in ph if v > price]
    supports = [v for v in pl if v < price]

    nearest_support = max(supports) if supports else None
    nearest_resistance = min(resistances) if resistances else None

    return nearest_support, nearest_resistance

def resistance_continuation(current_price, nearest_resistance, tolerance_pct=0.3):
    if not nearest_resistance:
        return False, False

    broken = current_price > nearest_resistance
    diff_pct = ((current_price - nearest_resistance) / nearest_resistance) * 100
    continuation = broken and diff_pct >= tolerance_pct

    return broken, continuation

def to_tr_timezone(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Istanbul"))

def detect_three_peaks(close_series):
    if close_series is None or close_series.empty or len(close_series) < 5:
        return False

    peaks = (
        (close_series.shift(1) < close_series) &
        (close_series.shift(-1) < close_series)
    )

    peak_prices = close_series[peaks]
    if len(peak_prices) < 3:
        return False

    last_three = peak_prices.iloc[-3:]
    max_peak = last_three.max()
    current_price = close_series.iloc[-1]

    return current_price > max_peak
