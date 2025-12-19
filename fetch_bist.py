import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

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
    ns, nr = nearest_support_resistance_from_history(df_15)
    resistance_continuation = False
    if tf15.get("resistance_break") and nr:
        resistance_continuation = price > nr
    three_peak = detect_three_peaks(df_15["Close"])
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
        "support_break": tf15.get("support_break"),
        "resistance_break": tf15.get("resistance_break"),
        "nearest_support": ns,
        "nearest_resistance": nr,
        "resistance_continuation": resistance_continuation,
        "tf": {
            "15m": tf15,
            "1h": tf1h,
            "4h": tf4h,
            "1d": tf1d
        },
        "super_combined_ok": super_ok,
    }


# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
cooldowns = {}
TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30

def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)

def in_cooldown(symbol):
    t = cooldowns.get(symbol)
    if not t:
        return False
    return now_tr() < t

def set_cooldown(symbol, minutes=COOLDOWN_MINUTES):
    cooldowns[symbol] = now_tr() + timedelta(minutes=minutes)

def clear_cooldown(symbol):
    cooldowns.pop(symbol, None)


# ==================================================
# TECH HELPERS
# ==================================================
def trend_ma_ok(tf):
    try:
        ma20 = tf.get("ma20")
        ma50 = tf.get("ma50")
        ma100 = tf.get("ma100")
        ma200 = tf.get("ma200")
        if not all([ma20, ma50, ma100, ma200]):
            return False, None
        golden = ma50 > ma200
        trend = ma20 > ma50 > ma100 > ma200
        return (trend or golden), {"ma20": ma20, "ma50": ma50, "ma100": ma100, "ma200": ma200, "golden_cross": golden}
    except Exception:
        return False, None

def volume_ok(tf15):
    v = tf15.get("volume")
    avg = tf15.get("volume_avg_5")
    if not v or not avg:
        return False, None
    return v > avg, {"volume": v, "avg": avg}


# ==================================================
# MESSAGE BUILDING
# ==================================================
def fmt_ma_dict(ma_dict):
    return ", ".join([f"{k}:{fmt_price(v)}" for k,v in ma_dict.items() if v])

def build_signal_message(item, sig_name, sig_type, trend_type, ma_dict):
    price = item.get("current_price")
    rsi = item.get("RSI")
    tf15 = item.get("tf", {}).get("15m", {})
    vol_ok, vol_data = volume_ok(tf15)
    vol_text = f"{vol_data['volume']} (Ort: {vol_data['avg']})" if vol_data else "N/A"
    nearest_resistance = item.get("nearest_resistance")
    nr_text = fmt_price(nearest_resistance) if nearest_resistance else "Yok"
    msg = (
        f"Hisse: {item['symbol']}\n"
        f"⚡ {sig_name}\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n"
        f"Hacim: {vol_text}\n"
        f"MA Değerleri: {fmt_ma_dict(ma_dict)}\n"
        f"Trend: {trend_type}\n"
        f"En yakın direnç (1h/4h/1d): {nr_text}\n\n"
        f"{fmt_nearest_sr(item)}"
    )
    return msg


# ==================================================
# LONG TERM TREND CHECK
# ==================================================
def long_term_trend_ok(item, price):
    trend_ok = False
    trend_type = ""
    tf_list = [("1h", item.get("tf", {}).get("1h", {})),
               ("4h", item.get("tf", {}).get("4h", {})),
               ("1d", item.get("tf", {}).get("1d", {}))]
    ma_dict = {}
    for name, tf in tf_list:
        ma20 = tf.get("ema20")
        ma50 = tf.get("ema50")
        ma100 = tf.get("ma100")
        ma200 = tf.get("ma200")
        ma_dict = {"MA20": ma20, "MA50": ma50, "MA100": ma100, "MA200": ma200}
        price_over_ma = any([ma and price > ma for ma in ma_dict.values() if ma])
        golden_cross = ma50 and ma200 and ma50 > ma200
        if price_over_ma or golden_cross:
            trend_ok = True
            trend_type = "Golden Cross" if golden_cross else "Uptrend"
            break
    return trend_ok, trend_type, ma_dict


# ==================================================
# SIGNAL DETECTORS
# ==================================================
def detect_pullback_buy(item):
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15.get("last_green"):
        return None
    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None
    price = item.get("current_price")
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    set_cooldown(symbol)
    msg = build_signal_message(item, "PULLBACK AL", "pullback", trend_type, ma_dict)
    return (f"PULL-{symbol}", msg, {"type": "pullback"})


def detect_super_combined(item, market_open=True):
    if not item.get("super_combined_ok") or not market_open:
        return None
    symbol = item["symbol"]
    price = item.get("current_price")
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if in_cooldown(symbol):
        return None
    register_signal(symbol, price)
    set_cooldown(symbol)
    msg = build_signal_message(item, "SÜPER KOMBİNE", "super", trend_type, ma_dict)
    return (f"SUPER-{symbol}", msg, {"type": "super"})


def detect_trend_breakout_buy(item):
    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None
    if not item.get("resistance_break"):
        return None
    tf15 = item.get("tf", {}).get("15m", {})
    rsi = item.get("RSI")
    if not rsi or rsi < 50 or rsi > 70:
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, item.get("current_price"))
    if not trend_ok:
        return None
    vol_ok, vol_data = volume_ok(tf15)
    if not vol_ok:
        return None
    price = item.get("current_price")
    nr = item.get("nearest_resistance")
    if nr and (nr - price) / price < 0.01:
        return None
    set_cooldown(symbol)
    msg = build_signal_message(item, "TREND + KIRILIM AL", "trend_breakout", trend_type, ma_dict)
    return (f"TREND-{symbol}", msg, {"type": "trend_breakout"})


def detect_kombine_buy(item, market_open=True):
    tf15 = item.get("tf", {}).get("15m", {})
    tf4h = item.get("tf", {}).get("4h", {})
    tf1d = item.get("tf", {}).get("1d", {})
    symbol = item["symbol"]
    price = item.get("current_price")
    kombine_ok = (
        tf1d.get("last_green") and
        tf4h.get("last_green") and
        tf15.get("last_green")
    )
    if not kombine_ok or not market_open:
        return None
    cooldown_key = f"{symbol}_kombine"
    if in_cooldown(cooldown_key):
        return None
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    set_cooldown(cooldown_key)
    msg = build_signal_message(item, "KOMBINED BUY", "kombine", trend_type, ma_dict)
    return ("KOMB-" + symbol, msg, {"type": "kombine"})


def detect_three_peak_break_buy(item):
    if not item.get("three_peak_break"):
        return None
    symbol = item["symbol"]
    price = item.get("current_price")
    rsi = item.get("RSI")
    tf15 = item.get("tf", {}).get("15m", {})
    trend_ok, trend_type, ma_dict = long_term_trend_ok(item, price)
    if not trend_ok:
        return None
    vol_ok, vol_data = volume_ok(tf15)
    rsi_ok = rsi and 50 <= rsi <= 70
    if trend_ok and vol_ok and rsi_ok:
        set_cooldown(symbol)
        msg = build_signal_message(item, "3 LU TEPE KIRILIMI AL", "three_peak_break", trend_type, ma_dict)
        return ("3PEAK-" + symbol, msg, {"type": "three_peak_break"})
    return None


# ==================================================
# PROCESS SIGNALS
# ==================================================
def process_signals(item, market_open=True):
    out = []
    for detector in [
        detect_pullback_buy,
        lambda i: detect_super_combined(i, market_open),
        detect_trend_breakout_buy,
        lambda i: detect_kombine_buy(i, market_open),
        detect_three_peak_break_buy
    ]:
        sig = detector(item)
        if sig:
            out.append(sig)
    return out


# ==================================================
# FETCH ALL BIST DATA
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
