from datetime import datetime
from utils import to_tr_timezone

# ----------------------------------------------------
# EMOJİ & FORMAT YARDIMCILARI
# ----------------------------------------------------

def ma_arrow(state):
    if state == "above":
        return "🔼 yukarı kırdı"
    if state == "below":
        return "🔻 aşağı kırdı"
    return "➡️ yatay"

def signal_emoji(sig):
    if sig == "AL":
        return "🟢⬆️"
    if sig == "SAT":
        return "🔴⬇️"
    return "⚪"

def format_sr(sr):
    if not sr:
        return "Veri yok"
    return (
        f"• 15m → Destek: {sr['15m']['support']} | Direnç: {sr['15m']['resistance']}\n"
        f"• 1h → Destek: {sr['1h']['support']} | Direnç: {sr['1h']['resistance']}\n"
        f"• 4h → Destek: {sr['4h']['support']} | Direnç: {sr['4h']['resistance']}\n"
        f"• 1D → Destek: {sr['1D']['support']} | Direnç: {sr['1D']['resistance']}"
    )

def nearest_resistance(sr, price):
    levels = []
    for tf in sr.values():
        if tf["resistance"] and tf["resistance"] > price:
            levels.append(tf["resistance"])
    return min(levels) if levels else None

# ----------------------------------------------------
# ANA MOTOR
# ----------------------------------------------------

def process_signals(item):
    signals = []
    symbol = item["symbol"]
    price = round(item["current_price"], 2)
    rsi = round(item["RSI"], 2)
    volume = item.get("volume")
    change = item.get("daily_change")
    ma = item.get("ma_breaks", {})
    sr = item.get("support_resistance")
    now = to_tr_timezone(datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------
    # NORMAL AL / SAT
    # ------------------------------------------------
    if item.get("last_signal"):
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"{signal_emoji(item['last_signal'])} {item['last_signal']} sinyali\n\n"
            f"Fiyat: {price} TL\n"
            f"RSI: {rsi}\n"
            f"Hacim: {volume}\n"
            f"Günlük Değişim: {change}\n\n"
            f"Sinyal zamanı (TR): {now}"
        )
        signals.append((f"{item['last_signal']}-{symbol}", msg))

    # ------------------------------------------------
    # KOMBİNE
    # ------------------------------------------------
    if item.get("composite_signal"):
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"🚀🚀🚀 Kombine Sinyal\n\n"
            f"Fiyat: {price} TL\n"
            f"RSI: {rsi}\n"
            f"Hacim: {volume}\n"
            f"Günlük Değişim: {change}\n\n"
            f"🔍 MA Durumları:\n"
            f"• MA20 → {ma_arrow(ma.get('MA20'))}\n"
            f"• MA50 → {ma_arrow(ma.get('MA50'))}\n"
            f"• MA100 → {ma_arrow(ma.get('MA100'))}\n"
            f"• MA200 → {ma_arrow(ma.get('MA200'))}\n\n"
            f"📉 Destek – Direnç:\n{format_sr(sr)}\n\n"
            f"Sinyal zamanı (TR): {now}"
        )
        signals.append((f"KOMBI-{symbol}", msg))

    # ------------------------------------------------
    # 🚀🚀🚀 SÜPER KOMBİNE (PUANLI)
    # ------------------------------------------------
    score = item.get("super_score", 0)
    if score >= 75:
        target = nearest_resistance(sr, price)
        target_msg = f"\n🎯 Hedef Fiyat: {target} TL" if target else ""

        msg = (
            f"Hisse Takip: {symbol}\n"
            f"🚀🚀🚀 SÜPER KOMBİNE SİNYAL\n\n"
            f"Skor: {score}/100\n\n"
            f"Fiyat: {price} TL\n"
            f"RSI: {rsi}\n"
            f"Hacim: {volume}\n"
            f"Günlük Değişim: {change}\n\n"
            f"🔍 MA Durumları:\n"
            f"• MA20 → {ma_arrow(ma.get('MA20'))}\n"
            f"• MA50 → {ma_arrow(ma.get('MA50'))}\n"
            f"• MA100 → {ma_arrow(ma.get('MA100'))}\n"
            f"• MA200 → {ma_arrow(ma.get('MA200'))}\n\n"
            f"📉 Destek – Direnç:\n{format_sr(sr)}"
            f"{target_msg}\n\n"
            f"Sinyal zamanı (TR): {now}"
        )
        signals.append((f"SUPER-{symbol}", msg))

    return signals
