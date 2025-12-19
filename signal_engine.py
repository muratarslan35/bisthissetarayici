from datetime import datetime, timezone, timedelta
from utils import to_tr_timezone

# ==================================================
# GLOBAL STATE
# ==================================================
success_tracker = {}
cooldowns = {}

TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30


# ==================================================
# HELPERS
# ==================================================
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


def set_cooldown(symbol):
    cooldowns[symbol] = now_tr() + timedelta(minutes=COOLDOWN_MINUTES)


def clear_cooldown(symbol):
    cooldowns.pop(symbol, None)


def fmt_nearest_sr(item):
    ns = item.get("nearest_support")
    nr = item.get("nearest_resistance")

    if not ns and not nr:
        return "📍 Yakın destek / direnç yok"

    txt = "📍 Yakın Seviyeler:\n"
    if ns:
        txt += f"• Destek: {fmt_price(ns)}\n"
    if nr:
        txt += f"• Direnç: {fmt_price(nr)}\n"

    if item.get("resistance_continuation"):
        txt += "🚀 Direnç kırıldı → devam potansiyeli\n"

    # çok yakın direnç uyarısı
    price = item.get("current_price")
    if nr and price and (nr - price) / price < 0.01:
        txt += "⚠️ Direnç çok yakın (riskli)\n"

    return txt.strip()


# ==================================================
# SUCCESS TRACKING
# ==================================================
def register_signal(symbol, price):
    today = now_tr().date()
    success_tracker.setdefault(today, {})
    if symbol not in success_tracker[today]:
        success_tracker[today][symbol] = {
            "entry": price,
            "target": price * (1 + TARGET_PCT),
            "hit": False,
            "last_price": price,
        }


def update_success(symbol, price):
    today = now_tr().date()
    d = success_tracker.get(today, {}).get(symbol)
    if not d:
        return None

    d["last_price"] = price
    if not d["hit"] and price >= d["target"]:
        d["hit"] = True
    return d["hit"]


# ==================================================
# TECH FILTERS
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

        return (trend or golden), {
            "ma20": ma20,
            "ma50": ma50,
            "ma100": ma100,
            "ma200": ma200,
            "golden_cross": golden
        }
    except Exception:
        return False, None


def volume_ok(tf15):
    v = tf15.get("volume")
    avg = tf15.get("volume_avg_5")
    if not v or not avg:
        return False, None
    return v > avg, {"volume": v, "avg": avg}


# ==================================================
# SIGNAL BLOCKS
# ==================================================
def detect_super_combined(item, market_open):
    if not item.get("super_combined_ok") or not market_open:
        return None

    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None

    price = item["current_price"]
    rsi = item["RSI"]

    register_signal(symbol, price)
    set_cooldown(symbol)

    msg = (
        f"Hisse: {symbol}\n"
        f"💎🚀 SÜPER KOMBİNE\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n\n"
        f"{fmt_nearest_sr(item)}"
    )

    return (f"SUPER-{symbol}", msg, {"type": "super"})


def detect_pullback_buy(item):
    tf15 = item.get("tf", {}).get("15m", {})
    if not tf15.get("last_green"):
        return None

    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None

    price = item["current_price"]
    rsi = item["RSI"]

    set_cooldown(symbol)

    msg = (
        f"Hisse: {symbol}\n"
        f"🟢 Pullback AL\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n\n"
        f"{fmt_nearest_sr(item)}"
    )

    return (f"PULL-{symbol}", msg, {"type": "pullback"})


def detect_sell_background(item):
    if not item.get("three_peak_break"):
        return None

    symbol = item["symbol"]
    clear_cooldown(symbol)  # BUY sonrası SELL gelirse cooldown iptal

    return None  # mesaj YOK


def detect_trend_breakout_buy(item):
    symbol = item["symbol"]
    if in_cooldown(symbol):
        return None

    if not item.get("resistance_break"):
        return None

    tf15 = item.get("tf", {}).get("15m", {})
    tf1h = item.get("tf", {}).get("1h", {})

    rsi = item.get("RSI")
    if not rsi or rsi < 50 or rsi > 70:
        return None

    trend_ok, ma = trend_ma_ok(tf1h)
    if not trend_ok:
        return None

    vol_ok, vol = volume_ok(tf15)
    if not vol_ok:
        return None

    price = item["current_price"]
    nr = item.get("nearest_resistance")
    if nr and (nr - price) / price < 0.01:
        return None

    set_cooldown(symbol)

    msg = (
        f"Hisse: {symbol}\n"
        f"🟢📈 TREND + KIRILIM AL\n\n"
        f"Fiyat: {fmt_price(price)} | RSI: {rsi:.2f}\n\n"
        f"MA20: {ma['ma20']:.2f}\n"
        f"MA50: {ma['ma50']:.2f}\n"
        f"MA100: {ma['ma100']:.2f}\n"
        f"MA200: {ma['ma200']:.2f}\n"
        f"{'Golden Cross' if ma['golden_cross'] else 'Trend Dizilimi'}\n\n"
        f"Hacim: {vol['volume']} (Ort: {vol['avg']})\n\n"
        f"{fmt_nearest_sr(item)}"
    )

    return (f"TREND-{symbol}", msg, {"type": "trend_breakout"})


# ==================================================
# CORE ENGINE
# ==================================================
def process_signals(item, market_open=True):
    out = []

    detect_sell_background(item)

    for fn in (
        detect_pullback_buy,
        lambda i: detect_super_combined(i, market_open),
        detect_trend_breakout_buy,
    ):
        sig = fn(item)
        if sig:
            out.append(sig)

    return out


def safe_process_bist_data(data_list, market_open=True):
    results = []
    if not data_list:
        return results

    for item in data_list:
        try:
            results.extend(process_signals(item, market_open))
        except Exception:
            continue

    return results


# ==================================================
# DAY END SUMMARY
# ==================================================
def daily_success_summary():
    today = now_tr().date()
    day = success_tracker.get(today)
    if not day:
        return None

    total = len(day)
    success = sum(1 for d in day.values() if d["hit"])

    lines = [
        "📊 GÜN SONU SİNYAL ÖZETİ",
        f"Toplam: {total}",
        f"Başarılı: {success}",
        f"Başarısız: {total - success}",
        "",
    ]

    for s, d in day.items():
        lines.append(
            f"{s} {'✅' if d['hit'] else '❌'} "
            f"{fmt_price(d['entry'])} → {fmt_price(d['last_price'])}"
        )

    return "\n".join(lines)

# ==================================================
    # KOMBINED BUY (SENİN ORİJİNAL ALGORİTMAN)
    # ==================================================
    kombine_ok = (
        tf1d.get("last_green")
        and tf4h.get("last_green")
        and tf15.get("last_green")
    )

    if kombine_ok and market_open:
        if not in_cooldown(symbol, "kombine"):
            nr = item.get("nearest_resistance")
            risk_ok = True
            if nr:
                risk_ok = (nr - price) / price >= MIN_RISK_DISTANCE_PCT

            if risk_ok:
                register_signal(symbol, price)

                msg = (
                    f"Hisse: {symbol}\n"
                    f"🟣 KOMBINED BUY\n\n"
                    f"1G + 4S + 15D YEŞİL TEYİT\n"
                    f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
                    f"{fmt_nearest_sr(item, for_buy=True)}"
                )

                set_cooldown(symbol, "kombine")
                out.append(("KOMB-" + symbol, msg, {"type": "kombine"}))
