import os
import time
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

from fetch_bist import fetch_bist_data
from signal_engine import (
    process_symbol_signals,
    format_signal_message,
    update_success_targets,
    SUCCESS_TRACKER,
    tr_now
)

from dashboard import (
    dashboard_bp,
    push_signal,
    push_success_signal
)

# ======================================================
# ZAMAN & SABİTLER
# ======================================================

TR_TZ = ZoneInfo("Europe/Istanbul")

BIST_OPEN = dtime(9, 40)
BIST_CLOSE = dtime(18, 10)

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# ======================================================
# TELEGRAM AYARLARI
# ======================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [v for k, v in os.environ.items() if k.startswith("TELEGRAM_CHAT_ID")]

TELEGRAM_ENABLED = bool(TELEGRAM_TOKEN and CHAT_IDS)

# ======================================================
# FLASK APP
# ======================================================

app = Flask(__name__)
app.register_blueprint(dashboard_bp)

# ======================================================
# ZAMAN YARDIMCILARI
# ======================================================

def now_tr():
    return datetime.now(TR_TZ)

def is_market_open(now=None):
    now = now or now_tr()
    # Hafta sonu kapalı
    if now.weekday() >= 5:  # Cumartesi=5, Pazar=6
        return False
    return BIST_OPEN <= now.time() <= BIST_CLOSE

# ======================================================
# TELEGRAM GÖNDERİMİ
# ======================================================

def send_telegram_message(text: str):
    if not TELEGRAM_ENABLED:
        return

    import requests

    for chat_id in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=5
            )
        except Exception as e:
            print("Telegram gönderim hatası:", e)

# ======================================================
# BAŞLANGIÇ MESAJI
# ======================================================

def send_startup_message():
    msg = (
        "🟢 <b>BIST TARAMA SİSTEMİ BAŞLATILDI</b>\n\n"
        f"🕒 Saat: {now_tr().strftime('%H:%M:%S')}\n"
        f"📅 Tarih: {now_tr().strftime('%d.%m.%Y')}\n\n"
        "📡 Tarama aktif."
    )
    send_telegram_message(msg)

# ======================================================
# GÜN SONU BAŞARI RAPORU
# ======================================================

def daily_success_summary():
    """
    Bugünkü tüm hedefleri özetler.
    """
    today = tr_now().date()
    hits = SUCCESS_TRACKER.get(today, {})
    lines = []
    for (symbol, algo), d in hits.items():
        if d.get("hit"):
            lines.append(f"{symbol} – {algo} → 🎯 Hedefe ulaştı")
    if not lines:
        return None
    return "📊 Günlük Başarı Raporu:\n" + "\n".join(lines)

def send_daily_success_report():
    report = daily_success_summary()
    if report:
        send_telegram_message(report)

# ======================================================
# ANA TARAMA DÖNGÜSÜ
# ======================================================

def scanner_loop():
    print("📡 Tarama döngüsü başladı")

    last_report_day = None

    while True:
        try:
            now = now_tr()

            # Market kapalıysa
            if not is_market_open(now):
                # Gün sonu raporu (1 kez)
                if last_report_day != now.date() and now.time() > BIST_CLOSE:
                    send_daily_success_report()
                    last_report_day = now.date()

                time.sleep(30)
                continue

            market_data = fetch_bist_data()

            for item in market_data:
                signals = process_symbol_signals(item)

                # fiyatla başarı hedefi güncelle
                successes = update_success_targets(
                    item["symbol"],
                    item["current_price"]
                )

                for s in successes:
                    push_success_signal({
                        "symbol": item["symbol"],
                        "algorithm": s["algorithm"],
                        "time": now.strftime("%H:%M:%S")
                    })

                for signal in signals:
                    # Dashboard
                    push_signal(signal)

                    # Telegram
                    msg = format_signal_message(signal)
                    send_telegram_message(msg)

        except Exception as e:
            print("Tarama hatası:", e)

        time.sleep(SCAN_INTERVAL)

# ======================================================
# SAĞLIK KONTROLÜ
# ======================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "time": now_tr().isoformat()
    })

# ======================================================
# APP START
# ======================================================

if __name__ == "__main__":
    threading.Thread(
        target=scanner_loop,
        daemon=True
    ).start()

    send_startup_message()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False
    )
