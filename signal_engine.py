from datetime import datetime, timezone
from utils import to_tr_timezone

# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
signal_cooldown = {}   # { symbol: {"type": "BUY", "ts": timestamp} }

TARGET_PCT = 0.02
COOLDOWN_SEC = 60 * 30   # 30 dk

MIN_RESISTANCE_DISTANCE_PCT = 0.01  # %1'den yakın direnç varsa BUY yok

# ==================================================
# HELPERS
# ==================================================
def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)


def cooldown_ok(symbol, sig_type):
    now = datetime.now().timestamp()
    last = signal_cooldown.get(symbol)

    if not last:
        return True

    # BUY sonrası SELL gelirse cooldown iptal
    if last["type"] == "BUY" and sig_type == "SELL":
        return True

    return (now - last["ts"]) > COOLDOWN_SEC


def register_cooldown(symbol, sig_type):
    signal_cooldown[symbol] = {
        "type": sig_type,
        "ts": datetime.now().timestamp()
    }


def fmt_nearest_sr(item, price):
    ns = item.get("nearest_support")
    nr = item.get("nearest_resistance")

    if not ns and not nr:
        return "📍 Yakın destek / direnç yok"

    txt = "📍 Yakın Seviyeler:\n"
    if ns:
        txt += f"• Destek: {fmt_price(ns)}\n"
    if nr:
        txt += f"• Direnç: {fmt_price(nr)}\n"

        dist = (nr - price) / price
        if dist < MIN_RESISTANCE_DISTANCE_PCT:
            txt += "⚠️ Direnç çok yakın (riskli)\n"

    if item.get("resistance_continuation"):
        txt += "🚀 Direnç kırıldı → devam potansiyeli\n"

    return txt.strip()

# ==================================================
# SUCCESS TRACKING
# ==================================================
def register_signal(symbol, price):
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    success_tracker.setdefault(today, {})

    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "last_price": price,
        }


def update_success(symbol, price):
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    d = success_tracker.get(today, {}).get(symbol)

    if not d:
        return None

    d["last_price"] = price
    if not d["hit"] and price >= d["target"]:
        d["hit"] = True

    return d["hit"]

# ==================================================
# CORE ENGINE
# ==================================================
def process_signals(item, market_open=True):
    out = []

    symbol = item["symbol"]
    price = float(item["current_price"])
    rsi = round(item["RSI"], 2)

    tf15 = item["tf"]["15m"]
    tf4h = item["tf"]["4h"]
    tf1d = item["tf"]["1d"]

    ema_ok = tf15.get("ema20") and tf15.get("ema50") and tf15["ema20"] > tf15["ema50"]
    volume_ok = tf15.get("volume") and tf15.get("volume_avg_5") and tf15["volume"] > tf15["volume_avg_5"]
    three_peak = item.get("three_peak_break")

    # ==================================================
    # SELL – 3LÜ TEPE
    # ==================================================
    if three_peak and cooldown_ok(symbol, "SELL"):
        msg = (
            f"Hisse: {symbol}\n"
            f"🔴 SAT – 3'LÜ TEPE\n\n"
            f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n"
            f"EMA20 < EMA50 veya tepe formasyonu\n\n"
            f"{fmt_nearest_sr(item, price)}"
        )
        register_cooldown(symbol, "SELL")
        out.append((f"SELL-{symbol}", msg, {"type": "sell"}))
        return out

    # ==================================================
    # KOMBINED BUY
    # ==================================================
    if (
        market_open
        and tf1d.get("last_green")
        and tf4h.get("last_green")
        and tf15.get("last_green")
        and ema_ok
        and volume_ok
        and not three_peak
        and cooldown_ok(symbol, "BUY")
    ):
        register_signal(symbol, price)
        register_cooldown(symbol, "BUY")

        msg = (
            f"Hisse: {symbol}\n"
            f"🟢 AL – KOMBINED\n\n"
            f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n"
            f"EMA20 > EMA50 | Hacim onaylı\n\n"
            f"{fmt_nearest_sr(item, price)}"
        )

        out.append((f"BUY-{symbol}", msg, {"type": "buy"}))
        return out

    # ==================================================
    # DİRENÇ KIRILIMI (BİLGİ)
    # ==================================================
    if item.get("resistance_break") and cooldown_ok(symbol, "RES"):
        msg = (
            f"Hisse: {symbol}\n"
            f"📈 Direnç Kırılımı\n\n"
            f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
            f"{fmt_nearest_sr(item, price)}"
        )
        register_cooldown(symbol, "RES")
        out.append((f"RES-{symbol}", msg, {"type": "resistance"}))

    return out


def safe_process_bist_data(data_list, market_open=True):
    results = []
    if not data_list:
        return results

    for item in data_list:
        try:
            sigs = process_signals(item, market_open)
            if sigs:
                results.extend(sigs)
        except Exception:
            continue

    return results
