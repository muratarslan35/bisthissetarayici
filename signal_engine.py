from datetime import datetime, timezone
from utils import to_tr_timezone

# ==================================================
# SUCCESS TRACKING (GÜN İÇİ TAKİP)
# ==================================================
success_tracker = {}

TARGET_PCT = 0.02   # %2 hedef (dokunulabilir ama şimdilik sabit)


# ==================================================
# HELPERS
# ==================================================
def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)


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
    """
    market_open:
      - Sabah ilk açılışta super kombine 15m oturmadan üretilmez
      - Gün içinde serbest
    """
    out = []

    symbol = item["symbol"]
    price = float(item["current_price"])
    rsi = round(item["RSI"], 2)

    # ----------------------------------------------
    # SUPER KOMBINED
    # ----------------------------------------------
    super_ok = item.get("super_combined_ok")

    if super_ok and market_open:
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

        out.append((
            f"SUPER-{symbol}",
            msg,
            {"type": "super"}
        ))

    # ----------------------------------------------
    # DİRENÇ KIRILIMI (TEK BAŞINA MESAJ)
    # ----------------------------------------------
    if item.get("resistance_break"):
        msg = (
            f"Hisse: {symbol}\n"
            f"📈 Direnç Kırılımı\n\n"
            f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
            f"{fmt_nearest_sr(item)}"
        )

        out.append((
            f"RES-{symbol}",
            msg,
            {"type": "resistance"}
        ))

    return out


# ==================================================
# SAFE WRAPPER (ÇÖKMESİN DİYE)
# ==================================================
def safe_process_bist_data(data_list, market_open=True):
    """
    fetch_bist_data() boş gelirse sistem çökmez
    """
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
# GÜN SONU ÖZET
# ==================================================
def daily_success_summary():
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    day_data = success_tracker.get(today)

    if not day_data:
        return None

    total = len(day_data)
    success = sum(1 for d in day_data.values() if d["hit"])

    lines = [
        "📊 GÜN SONU SİNYAL ÖZETİ",
        f"Toplam sinyal: {total}",
        f"Başarılı: {success}",
        f"Başarısız: {total - success}",
        "",
        "Detaylar:"
    ]

    for sym, d in day_data.items():
        status = "✅" if d["hit"] else "❌"
        lines.append(
            f"{sym} {status} | Giriş: {fmt_price(d['entry'])} → "
            f"Son: {fmt_price(d['last_price'])}"
        )

    return "\n".join(lines)
