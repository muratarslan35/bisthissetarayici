from datetime import datetime, timezone
from utils import to_tr_timezone

# ==================================================
# SUCCESS TRACKING
# ==================================================
success_tracker = {}

# ==================================================
# HELPERS
# ==================================================
def ma_text(v):
    return {
        "above": "🔼 yukarı kırdı",
        "below": "🔻 aşağı kırdı",
        "golden_cross": "⚔️ Golden Cross",
        "death_cross": "☠️ Death Cross"
    }.get(v, "➡️ yatay")

def fmt_support_resistance(sr):
    if not sr:
        return "Destek/Direnç verisi yok"
    return (
        f"• 15m → D: {sr['15m']['support']} | R: {sr['15m']['resistance']}\n"
        f"• 1h → D: {sr['1h']['support']} | R: {sr['1h']['resistance']}\n"
        f"• 4h → D: {sr['4h']['support']} | R: {sr['4h']['resistance']}\n"
        f"• 1D → D: {sr['1D']['support']} | R: {sr['1D']['resistance']}"
    )

# ==================================================
# SUCCESS LOGIC
# ==================================================
def register_signal(symbol, price):
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    success_tracker.setdefault(symbol, {})
    if today not in success_tracker[symbol]:
        success_tracker[symbol][today] = {
            "entry": price,
            "target": price * 1.02,
            "hit": False
        }

def check_success(symbol, price):
    today = to_tr_timezone(datetime.now(timezone.utc)).date()
    d = success_tracker.get(symbol, {}).get(today)
    if not d:
        return None
    if not d["hit"] and price >= d["target"]:
        d["hit"] = True
    return "BAŞARILI ✅" if d["hit"] else "BAŞARISIZ ❌"

# ==================================================
# CORE SIGNAL ENGINE (DEĞİŞMEDİ)
# ==================================================
def process_signals(item):
    out = []

    symbol = item["symbol"]
    price = float(item["current_price"])
    rsi = round(item["RSI"], 2)
    ma = item.get("ma_breaks", {})
    sr = item.get("support_resistance")

    # 🔧 UYUM: super_combined_ok → super_score
    if item.get("super_combined_ok"):
        score = 85
    else:
        score = None

    success = check_success(symbol, price)

    if score and score >= 80:
        register_signal(symbol, price)

        msg = (
            f"Hisse: {symbol}\n"
            f"💎🚀 SÜPER KOMBİNE\n"
            f"Puan: {score}/100\n"
            f"{'🎯 ' + success if success else ''}\n\n"
            f"Fiyat: {price} | RSI: {rsi}\n\n"
            f"{fmt_support_resistance(sr)}"
        )

        out.append((f"SUPER-{symbol}", msg, {"type": "super"}))

    return out

# ==================================================
# 🔒 SAFE WRAPPER (YENİ – AMA ALGORİTMAYA DOKUNMAZ)
# ==================================================
def safe_process_bist_data(data_list):
    """
    fetch_bist_data() boş veya None dönerse sistem çökmesin.
    Her item için process_signals() çağrılır.
    """
    results = []

    if not data_list:
        return results

    for item in data_list:
        try:
            sigs = process_signals(item)
            if sigs:
                results.extend(sigs)
        except Exception:
            continue

    return results
