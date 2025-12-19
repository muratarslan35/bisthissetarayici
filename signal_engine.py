from datetime import datetime, timezone, timedelta
from utils import to_tr_timezone

# ==================================================
# CONFIG
# ==================================================
TARGET_PCT = 0.02
COOLDOWN_MINUTES = 30
MIN_RISK_DISTANCE_PCT = 0.005   # %0.5'ten yakın direnç varsa BUY yok

# ==================================================
# STATE
# ==================================================
success_tracker = {}          # gün içi başarı
cooldown_tracker = {}         # { (symbol, signal_type): last_time }

# ==================================================
# HELPERS
# ==================================================
def now_tr():
    return to_tr_timezone(datetime.now(timezone.utc))

def in_cooldown(symbol, sig_type):
    key = (symbol, sig_type)
    t = cooldown_tracker.get(key)
    if not t:
        return False
    return (now_tr() - t) < timedelta(minutes=COOLDOWN_MINUTES)

def set_cooldown(symbol, sig_type):
    cooldown_tracker[(symbol, sig_type)] = now_tr()

def clear_cooldown(symbol, sig_type):
    cooldown_tracker.pop((symbol, sig_type), None)

def fmt_price(v):
    try:
        return f"{v:.2f}"
    except Exception:
        return str(v)

# ==================================================
# SUPPORT / RESISTANCE TEXT
# ==================================================
def fmt_nearest_sr(item, for_buy=False):
    ns = item.get("nearest_support")
    nr = item.get("nearest_resistance")
    price = item.get("current_price")

    if not ns and not nr:
        return "📍 Yakın destek / direnç yok"

    txt = "📍 Yakın Seviyeler:\n"
    if ns:
        txt += f"• Destek: {fmt_price(ns)}\n"
    if nr:
        txt += f"• Direnç: {fmt_price(nr)}\n"

    if for_buy and nr and price:
        dist = (nr - price) / price
        if dist < MIN_RISK_DISTANCE_PCT:
            txt += "⚠️ Direnç çok yakın (riskli)\n"

    if item.get("resistance_continuation"):
        txt += "🚀 Direnç kırıldı → devam potansiyeli\n"

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
# CORE SIGNAL ENGINE
# ==================================================
def process_signals(item, market_open=True):
    out = []

    symbol = item["symbol"]
    price = float(item["current_price"])
    rsi = round(item["RSI"], 2)

    tf15 = item.get("tf", {}).get("15m", {})
    tf1h = item.get("tf", {}).get("1h", {})
    tf4h = item.get("tf", {}).get("4h", {})
    tf1d = item.get("tf", {}).get("1d", {})

    # ==================================================
    # EMA / TREND FLAGS (ESKİDEN VAR)
    # ==================================================
    ema_buy_ok = (
        tf15.get("last_green")
        and tf4h.get("last_green")
        and tf1d.get("last_green")
    )

    ema_sell_ok = item.get("three_peak_break") or (
        not tf15.get("last_green")
        and not tf4h.get("last_green")
    )

    # ==================================================
    # SELL – 3'LÜ TEPE / EMA
    # ==================================================
    if ema_sell_ok:
        if not in_cooldown(symbol, "sell"):
            msg = (
                f"Hisse: {symbol}\n"
                f"🔴 SAT – 3'LÜ TEPE / EMA\n\n"
                f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n"
                f"EMA20 < EMA50 veya tepe formasyonu\n\n"
                f"{fmt_nearest_sr(item)}"
            )

            # BUY cooldown iptali
            clear_cooldown(symbol, "buy")
            clear_cooldown(symbol, "kombine")

            set_cooldown(symbol, "sell")
            out.append(("SELL-" + symbol, msg, {"type": "sell"}))

    # ==================================================
    # BUY – EMA + TREND
    # ==================================================
    if ema_buy_ok:
        if not in_cooldown(symbol, "buy"):
            nr = item.get("nearest_resistance")
            risk_ok = True
            if nr:
                risk_ok = (nr - price) / price >= MIN_RISK_DISTANCE_PCT

            if risk_ok:
                register_signal(symbol, price)
                success = update_success(symbol, price)

                msg = (
                    f"Hisse: {symbol}\n"
                    f"🟢 AL – EMA / TREND\n\n"
                    f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
                    f"{fmt_nearest_sr(item, for_buy=True)}"
                )

                if success:
                    msg += "\n🎯 HEDEF GERÇEKLEŞTİ (%2)"

                set_cooldown(symbol, "buy")
                out.append(("BUY-" + symbol, msg, {"type": "buy"}))

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

    # ==================================================
    # SUPER KOMBINED
    # ==================================================
    if item.get("super_combined_ok") and market_open:
        if not in_cooldown(symbol, "super"):
            register_signal(symbol, price)
            success = update_success(symbol, price)

            msg = (
                f"Hisse: {symbol}\n"
                f"💎🚀 SÜPER KOMBİNE\n\n"
                f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
                f"{fmt_nearest_sr(item, for_buy=True)}"
            )

            if success:
                msg += "\n🎯 HEDEF GERÇEKLEŞTİ (%2)"

            set_cooldown(symbol, "super")
            out.append(("SUPER-" + symbol, msg, {"type": "super"}))

    # ==================================================
    # DİRENÇ KIRILIMI (TEK BAŞINA)
    # ==================================================
    if item.get("resistance_break"):
        if not in_cooldown(symbol, "resistance"):
            msg = (
                f"Hisse: {symbol}\n"
                f"📈 Direnç Kırılımı\n\n"
                f"Fiyat: {fmt_price(price)} | RSI: {rsi}\n\n"
                f"{fmt_nearest_sr(item)}"
            )
            set_cooldown(symbol, "resistance")
            out.append(("RES-" + symbol, msg, {"type": "resistance"}))

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
# GÜN SONU ÖZET
# ==================================================
def daily_success_summary():
    today = now_tr().date()
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
