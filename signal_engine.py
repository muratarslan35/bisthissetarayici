from datetime import datetime, timezone, timedelta
from utils import to_tr_timezone

# ==================================================
# CONFIG
# ==================================================
TARGET_PCT = 0.02           # %2 hedef
COOLDOWN_MINUTES = 30       # aynı sinyal tekrar süresi
MIN_RESISTANCE_DIST = 0.01  # %1'den yakın dirençte AL üretme

# ==================================================
# STATE
# ==================================================
success_tracker = {}
signal_cooldowns = {}  # { (symbol, type): datetime }

# ==================================================
# HELPERS
# ==================================================
def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)


def cooldown_ok(symbol, sig_type):
    key = (symbol, sig_type)
    last = signal_cooldowns.get(key)
    if not last:
        return True
    return datetime.now(timezone.utc) - last > timedelta(minutes=COOLDOWN_MINUTES)


def set_cooldown(symbol, sig_type):
    signal_cooldowns[(symbol, sig_type)] = datetime.now(timezone.utc)


def clear_cooldown(symbol, sig_type):
    signal_cooldowns.pop((symbol, sig_type), None)


def too_close_to_resistance(price, resistance):
    if not resistance or not price:
        return False
    return (resistance - price) / price < MIN_RESISTANCE_DIST


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

    return txt.strip()


# ==================================================
# SUCCESS LOGIC
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
# CORE SIGNAL ENGINE
# ==================================================
def process_signals(item, market_open=True):
    out = []

    symbol = item["symbol"]
    price = float(item["current_price"])
    rsi = round(item["RSI"], 2)
    resistance = item.get("nearest_resistance")

    # ==================================================
    # SUPER KOMBINASYON
    # ==================================================
    if item.get("super_combined_ok") and market_open:

        # 🔒 çok yakın direnç filtresi
        if too_close_to_resistance(price, resistance):
            pass
        elif cooldown_ok(symbol, "super"):
            register_signal(symbol, price)
            success = update_success(symbol, price)

            msg = (
                f"Hisse: {symbol}\n"
                f"💎🚀 SÜPER KOMBİNE\n\n"
                f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
                f"{fmt_nearest_sr(item)}"
            )

            if success:
                msg += "\n🎯 HEDEF GERÇEKLEŞTİ (%2)"

            out.append((f"SUPER-{symbol}", msg, {"type": "super"}))
            set_cooldown(symbol, "super")

    # ==================================================
    # DİRENÇ KIRILIMI
    # ==================================================
    if item.get("resistance_break") and cooldown_ok(symbol, "resistance"):
        msg = (
            f"Hisse: {symbol}\n"
            f"📈 Direnç Kırılımı\n\n"
            f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
            f"{fmt_nearest_sr(item)}"
        )

        out.append((f"RES-{symbol}", msg, {"type": "resistance"}))
        set_cooldown(symbol, "resistance")

        # 🔓 direnç kırıldıysa BUY cooldown iptal
        clear_cooldown(symbol, "super")

    return out


# ==================================================
# SAFE WRAPPER
# ==================================================
def safe_process_bist_data(data_list, market_open=True):
    results = []
    if not data_list:
        return results

    for item in data_list:
        try:
            sigs = process_signals(item, market_open=market_open)
            if sigs:
                results.extend(sigs)
        except Exception:
            continue

    return results


# ==================================================
# DAILY SUMMARY
# ==================================================
def daily_success_summary():
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    day = success_tracker.get(today)
    if not day:
        return None

    total = len(day)
    success = sum(1 for d in day.values() if d["hit"])

    lines = [
        "📊 GÜN SONU SİNYAL ÖZETİ",
        f"Toplam sinyal: {total}",
        f"Başarılı: {success}",
        f"Başarısız: {total - success}",
        "",
        "Detaylar:"
    ]

    for sym, d in day.items():
        status = "✅" if d["hit"] else "❌"
        lines.append(
            f"{sym} {status} | Giriş: {fmt_price(d['entry'])} → "
            f"Son: {fmt_price(d['last_price'])}"
        )

    return "\n".join(lines)
