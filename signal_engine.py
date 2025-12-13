from datetime import datetime, timezone
from utils import to_tr_timezone

# --------------------------------------------------
# EMOJI & FORMAT HELPERS
# --------------------------------------------------

def ma_text(v):
    if v == "above":
        return "🔼 yukarı kırdı"
    if v == "below":
        return "🔻 aşağı kırdı"
    if v == "golden_cross":
        return "⚔️ Golden Cross"
    if v == "death_cross":
        return "☠️ Death Cross"
    return "➡️ yatay"

def fmt_support_resistance(sr):
    if not sr:
        return "Destek/Direnç verisi yok"
    return (
        f"• 15m → D: {sr['15m']['support']} | R: {sr['15m']['resistance']}\n"
        f"• 1h → D: {sr['1h']['support']} | R: {sr['1h']['resistance']}\n"
        f"• 4h → D: {sr['4h']['support']} | R: {sr['4h']['resistance']}\n"
        f"• 1D → D: {sr['1D']['support']} | R: {sr['1D']['resistance']}"
    )

# --------------------------------------------------
# MAIN ENGINE
# --------------------------------------------------

def process_signals(item):
    """
    ÇIKTI:
    [
      (sig_key, telegram_message),
      ...
    ]
    """
    out = []

    symbol = item["symbol"]
    price = item["current_price"]
    rsi = round(item["RSI"], 2)
    trend = item["trend"]
    volume = item.get("volume")
    change = item.get("daily_change")

    ma = item.get("ma_breaks", {})
    sr = item.get("support_resistance")
    ts = to_tr_timezone(datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")

    # --------------------------------------------------
    # MA BLOĞU
    # --------------------------------------------------
    ma_block = (
        f"MA Durumları:\n"
        f"{ma_text(ma.get('MA20'))} MA20\n"
        f"{ma_text(ma.get('MA50'))} MA50\n"
        f"{ma_text(ma.get('MA100'))} MA100\n"
        f"{ma_text(ma.get('MA200'))} MA200"
    )

    # --------------------------------------------------
    # TEMEL AL / SAT
    # --------------------------------------------------
    if item.get("last_signal") == "AL":
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"🟢⬆️ AL Sinyali\n"
            f"Fiyat: {price} TL | RSI: {rsi}\n"
            f"Günlük Değişim: {change} | Hacim: {volume}\n\n"
            f"{ma_block}\n\n"
            f"📉 Destek – Direnç:\n{fmt_support_resistance(sr)}\n\n"
            f"Sinyal zamanı (TR): {ts}"
        )
        out.append((f"AL-{symbol}", msg))

    if item.get("last_signal") == "SAT":
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"🔴⬇️ SAT Sinyali\n"
            f"Fiyat: {price} TL | RSI: {rsi}\n"
            f"Günlük Değişim: {change} | Hacim: {volume}\n\n"
            f"{ma_block}\n\n"
            f"📉 Destek – Direnç:\n{fmt_support_resistance(sr)}\n\n"
            f"Sinyal zamanı (TR): {ts}"
        )
        out.append((f"SAT-{symbol}", msg))

    # --------------------------------------------------
    # FORMASYONLAR
    # --------------------------------------------------
    if item.get("three_peak_break"):
        out.append((
            f"3PEAK-{symbol}",
            f"Hisse Takip: {symbol}\n🔥🔥 3’lü tepe kırılımı!\nSinyal zamanı (TR): {ts}"
        ))

    # --------------------------------------------------
    # KOMBİNE SİNYAL
    # --------------------------------------------------
    if item.get("composite_signal") == "A":
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"🚀🚀🚀 Kombine Sinyal\n"
            f"Fiyat: {price} TL | RSI: {rsi}\n"
            f"Günlük Değişim: {change} | Hacim: {volume}\n\n"
            f"{ma_block}\n\n"
            f"📉 Destek – Direnç:\n{fmt_support_resistance(sr)}\n\n"
            f"Sinyal zamanı (TR): {ts}"
        )
        out.append((f"COMBO-{symbol}", msg))

    # --------------------------------------------------
    # SÜPER KOMBİNE (puanlı)
    # --------------------------------------------------
    score = item.get("super_score")
    if score and score >= 80:
        msg = (
            f"Hisse Takip: {symbol}\n"
            f"💎🚀 SÜPER KOMBİNE SİNYAL\n"
            f"Puan: {score}/100\n"
            f"Fiyat: {price} TL | RSI: {rsi}\n"
            f"Günlük Değişim: {change} | Hacim: {volume}\n\n"
            f"{ma_block}\n\n"
            f"📉 Destek – Direnç:\n{fmt_support_resistance(sr)}\n\n"
            f"Sinyal zamanı (TR): {ts}"
        )
        out.append((f"SUPER-{symbol}", msg))

    return out
