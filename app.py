import os
from dotenv import load_dotenv
import time
import threading
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template

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
# .env DOSYASINI YÜKLE
# ======================================================
load_dotenv()

# ======================================================
# ZAMAN & SABİTLER
# ======================================================
TR_TZ = ZoneInfo("Europe/Istanbul")

# BIST GERÇEK SÜREKLİ İŞLEM SAATLERİ
BIST_OPEN = dtime(9, 55)
BIST_CLOSE = dtime(18, 0)

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

@app.route("/")
def index():
    return render_template("dashboard.html")

# ======================================================
# ZAMAN YARDIMCILARI
# ======================================================
def now_tr():
    return datetime.now(TR_TZ)

def is_market_open(now=None):
    now = now or datetime.now(TR_TZ)

    # Hafta sonu kapalı
    if now.weekday() >= 5:
        return False

    return BIST_OPEN <= now.time() <= BIST_CLOSE

# ======================================================
# TELEGRAM GÖNDERİMİ
# ======================================================
def send_telegram_message(text: str):
    if not TELEGRAM_ENABLED:
        print("⚠ Telegram kapalı veya token/chat ID eksik")
        return

    import requests

    for chat_id in CHAT_IDS:
        try:
            res = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=5
            )
            if res.status_code == 200:
                print("✅ Telegram mesaj gönderildi")
            else:
                print(f"⚠ Telegram hata kodu: {res.status_code}")
        except Exception as e:
            print("⚠ Telegram exception:", e)

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
    print("📡 Startup mesajı gönderiliyor...")
    send_telegram_message(msg)

# ======================================================
# GÜN SONU BAŞARI RAPORU
# ======================================================
def daily_success_summary():
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
    send_startup_message()

    last_report_day = None
    failed_symbols = set()

    while True:
        try:
            now = now_tr()
            print(f"⏱ Döngü: {now.strftime('%H:%M:%S')}")

            if not is_market_open(now):
                print("⏹ Piyasa kapalı")
                if last_report_day != now.date() and now.time() > BIST_CLOSE:
                    send_daily_success_report()
                    last_report_day = now.date()
                time.sleep(30)
                continue

            print("✅ MARKET AÇIK → TARAMA BAŞLADI")

            market_data = fetch_bist_data()
            print(f"📈 Tarama sonucu: {len(market_data)} hisse")

            for item in market_data:
                symbol = item["symbol"]
                if symbol in failed_symbols:
                    continue

                try:
                    signals = process_symbol_signals(item)
                    successes = update_success_targets(symbol, item["current_price"])

                    for s in successes:
                        push_success_signal({
                            "symbol": symbol,
                            "algorithm": s["algorithm"],
                            "time": now.strftime("%H:%M:%S")
                        })

                    for signal in signals:
                        push_signal(signal)
                        send_telegram_message(format_signal_message(signal))

                except Exception:
                    failed_symbols.add(symbol)

        except Exception as e:
            print("⚠ Tarama hatası:", e)

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

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False
    )
