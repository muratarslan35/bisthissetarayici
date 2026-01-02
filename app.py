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
# ENV
# ======================================================
load_dotenv()

# ======================================================
# TIME / BIST HOURS (TEK KAYNAK)
# ======================================================
TR_TZ = ZoneInfo("Europe/Istanbul")

# BIST SÜREKLİ İŞLEM
BIST_OPEN = dtime(9, 40)
BIST_CLOSE = dtime(18, 5)

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# ======================================================
# TELEGRAM
# ======================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [v for k, v in os.environ.items() if k.startswith("TELEGRAM_CHAT_ID")]
TELEGRAM_ENABLED = bool(TELEGRAM_TOKEN and CHAT_IDS)

# ======================================================
# FLASK
# ======================================================
app = Flask(__name__)
app.register_blueprint(dashboard_bp)

@app.route("/")
def index():
    return render_template("dashboard.html")

# ======================================================
# HELPERS
# ======================================================
def now_tr():
    return datetime.now(TR_TZ)

def is_market_open(now=None):
    now = now or now_tr()
    if now.weekday() >= 5:
        return False
    return BIST_OPEN <= now.time() <= BIST_CLOSE

# ======================================================
# TELEGRAM
# ======================================================
def send_telegram_message(text: str):
    if not TELEGRAM_ENABLED:
        print("⚠ Telegram kapalı")
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
            print("⚠ Telegram hata:", e)

# ======================================================
# STARTUP
# ======================================================
def send_startup_message():
    msg = (
        "🟢 <b>BIST TARAMA SİSTEMİ BAŞLATILDI</b>\n\n"
        f"🕒 {now_tr().strftime('%H:%M:%S')} | {now_tr().strftime('%d.%m.%Y')}\n"
        "📡 Scanner aktif"
    )
    print("📡 Startup mesajı gönderiliyor")
    send_telegram_message(msg)

# ======================================================
# DAILY REPORT
# ======================================================
def daily_success_summary():
    today = tr_now().date()
    hits = SUCCESS_TRACKER.get(today, {})
    lines = [
        f"{s} – {a} 🎯"
        for (s, a), d in hits.items()
        if d.get("hit")
    ]
    if not lines:
        return None
    return "📊 Gün Sonu Başarı Raporu\n" + "\n".join(lines)

def send_daily_success_report():
    report = daily_success_summary()
    if report:
        send_telegram_message(report)

# ======================================================
# SCANNER LOOP (ANA MOTOR)
# ======================================================
def scanner_loop():
    print("📡 Scanner thread BAŞLADI")
    send_startup_message()

    last_report_day = None

    while True:
        now = now_tr()
        print(f"⏱ Döngü tick: {now.strftime('%H:%M:%S')}")

        try:
            if not is_market_open(now):
                print("⏹ Market kapalı – beklemede")
                if last_report_day != now.date() and now.time() > BIST_CLOSE:
                    send_daily_success_report()
                    last_report_day = now.date()
                time.sleep(30)
                continue

            print("✅ MARKET AÇIK → TARAMA BAŞLIYOR")

            market_data = fetch_bist_data()
            print(f"📈 Taranan hisse: {len(market_data)}")

            for item in market_data:
                symbol = item["symbol"]

                try:
                    signals = process_symbol_signals(item)
                    successes = update_success_targets(
                        symbol, item["current_price"]
                    )

                    for s in successes:
                        push_success_signal({
                            "symbol": symbol,
                            "algorithm": s["algorithm"],
                            "time": now.strftime("%H:%M:%S")
                        })

                    for signal in signals:
                        push_signal(signal)
                        send_telegram_message(
                            format_signal_message(signal)
                        )

                except Exception as e:
                    print(f"⚠ {symbol} işlenirken hata:", e)

        except Exception as e:
            print("🔥 Scanner genel hata:", e)

        time.sleep(SCAN_INTERVAL)

# ======================================================
# HEALTH
# ======================================================
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "time": now_tr().isoformat(),
        "market_open": is_market_open()
    })

# ======================================================
# START
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
