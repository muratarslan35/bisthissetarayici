from datetime import datetime
from utils import to_tr_timezone

# =====================================================
# EMOJI & FORMAT YARDIMCILARI
# =====================================================

def ma_text(state):
    if state == "above":
        return "🔼 yukarı kırdı"
    if state == "below":
        return "🔻 aşağı kırdı"
    return "➡️ yatay"

def buy_sell_emoji(sig):
    if sig == "AL":
        return "🟢⬆️ AL"
    if sig == "SAT":
        return "🔴⬇️ SAT"
    return "⚪ NÖTR"

def fmt(val):
    try:
        return f"{val:.2f}"
    except:
        return str(val)

# =====================================================
# ANA SİNYAL MOTORU
# =====================================================

def process_signals(item):
    """
    HER HİSSE İÇİN:
    - SADECE 1 ADET TELEGRAM MESAJI ÜRETİR
    - TÜM SİNYALLER TEK BLOKTA
    """

    signals = []

    symbol = item.get("symbol")
    price = item.get("current_price")
    rsi = item.get("RSI")
    volume = item.get("volume")
    daily_change = item.get("daily_change")

    ma = item.get("ma_breaks", {})
    trend = item.get("trend")
    last_signal = item.get("last_signal")

    support = item.get("nearest_support")
    resistance = item.get("nearest_resistance")

    green_11 = item.get("green_mum_11")
    green_15 = item.get("green_mum_15")

    three_peak = item.get("three_peak_break")
    support_break = item.get("support_break")
    resistance_break = item.get("resistance_break")

    combo = item.get("composite_signal")
    super_combo = item.get("super_composite_signal")
    score = item.get("super_score")

    tr_time = to_tr_timezone(datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")

    # =====================================================
    # BAŞLIK
    # =====================================================

    msg = []
    msg.append(f"<b>📊 Hisse Takip: {symbol}</b>")
    msg.append("")

    # =====================================================
    # AL / SAT
    # =====================================================
    if last_signal:
        msg.append(f"{buy_sell_emoji(last_signal)} sinyali")

    # =====================================================
    # FORMASYONLAR
    # =====================================================
    if resistance_break:
        msg.append("🔴 Direnç kırılımı")

    if support_break:
        msg.append("🟢 Destek kırılımı")

    if three_peak:
        msg.append("🔥🔥 3’lü tepe kırılımı")

    # =====================================================
    # MUM BİLGİLERİ (kombine için kalıyor)
    # =====================================================
    if green_11:
        msg.append("✅ 11:00 yeşil mum")

    if green_15:
        msg.append("✅ 15:00 yeşil mum")

    # =====================================================
    # MA DURUMLARI
    # =====================================================
    msg.append("")
    msg.append("<b>📈 MA Durumları</b>")
    msg.append(f"• MA20  : {ma_text(ma.get('MA20'))}")
    msg.append(f"• MA50  : {ma_text(ma.get('MA50'))}")
    msg.append(f"• MA100 : {ma_text(ma.get('MA100'))}")
    msg.append(f"• MA200 : {ma_text(ma.get('MA200'))}")

    if ma.get("20x50") == "golden_cross":
        msg.append("⚔️ Golden Cross (20/50)")

    # =====================================================
    # DESTEK / DİRENÇ
    # =====================================================
    msg.append("")
    msg.append("<b>📉 Destek / Direnç</b>")
    if support and resistance:
        msg.append(f"🟢 Destek : {fmt(support)}")
        msg.append(f"🔴 Direnç : {fmt(resistance)}")

        if resistance and price and resistance > price:
            target = fmt(resistance)
            msg.append(f"🎯 Hedef fiyat : {target}")
    else:
        msg.append("Veri yok")

    # =====================================================
    # KOMBİNE SİNYALLER
    # =====================================================
    if combo:
        msg.append("")
        msg.append("🚀🚀🚀 <b>Kombine Sinyal</b>")

    if super_combo:
        msg.append("")
        msg.append("🧠🔥 <b>SÜPER KOMBİNE SİNYAL</b>")
        msg.append(f"⭐ Güç Puanı : {score}/100")

    # =====================================================
    # FİYAT / HACİM / RSI
    # =====================================================
    msg.append("")
    msg.append(f"💰 Fiyat : {fmt(price)} TL")
    msg.append(f"📊 RSI   : {fmt(rsi)}")
    msg.append(f"📦 Hacim : {volume}")
    msg.append(f"📈 Günlük Değişim : {daily_change}")
    msg.append(f"📌 Trend : {trend}")

    # =====================================================
    # ZAMAN
    # =====================================================
    msg.append("")
    msg.append(f"⏰ <i>Sinyal zamanı (TR): {tr_time}</i>")

    final_message = "\n".join(msg)

    signals.append((f"MAIN-{symbol}", final_message))
    return signals
