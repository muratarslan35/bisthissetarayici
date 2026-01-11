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
    update_success_targets,
    format_signal_message,
    build_daily_success_report,
    build_weekly_success_report,
    reset_daily_success_if_needed,
    reset_weekly_success_if_needed,
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
# TIME / BIST HOURS
# ======================================================
TR_TZ = ZoneInfo("Europe/Istanbul")

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
        except Exception:
            pass

# ======================================================
# STARTUP
# ======================================================
def send_startup_message():
    send_telegram_message(
        "🟢 <b>DUYGULARDAN ARINDIRILMIŞ HAS ADANALI BOT BAŞLATILDI😎</b>\n"
        f"🕒 {now_tr().strftime('%H:%M:%S')} | {now_tr().strftime('%d.%m.%Y')}"
    )

# ======================================================
# SCANNER LOOP
# ======================================================
def scanner_loop():
    send_startup_message()

    last_daily_report = None
    last_weekly_report = None
    last_close_snapshot_date = None

    while True:
        now = now_tr()
        print(f"\n⏱ Döngü: {now.strftime('%H:%M:%S')}", flush=True)

        # 🔁 RESETLER
        reset_daily_success_if_needed()
        reset_weekly_success_if_needed()

        try:
            # ==================================================
            # MARKET KAPALI
            # ==================================================
            if not is_market_open(now):
                print("⏹ Market kapalı", flush=True)

                # 🔒 TEK SEFERLİK KAPANIŞ SNAPSHOT (18:10+)
                if (
                    now.time() >= dtime(18, 10)
                    and last_close_snapshot_date != now.date()
                ):
                    try:
                        print("📌 Kapanış snapshot alınıyor...", flush=True)
                        market_data = fetch_bist_data()

                        for item in market_data:
                            symbol = item["symbol"]
                            price = item["current_price"]
                            update_success_targets(symbol, price)

                        last_close_snapshot_date = now.date()
                        print("✅ Kapanış snapshot tamamlandı", flush=True)

                    except Exception as e:
                        print("🔥 Kapanış snapshot hatası:", e, flush=True)

                # 🟢 GÜNLÜK RAPOR (1 KERE)
                if (
                    last_daily_report != now.date()
                    and now.time() > BIST_CLOSE
                ):
                    report = build_daily_success_report()
                    if report:
                        send_telegram_message(report)
                    last_daily_report = now.date()

                time.sleep(30)
                continue

            # ==================================================
            # MARKET AÇIK
            # ==================================================
            print("✅ MARKET AÇIK → TARAMA", flush=True)

            market_data = fetch_bist_data()
            print(f"📈 Hisse sayısı: {len(market_data)}", flush=True)

            for item in market_data:
                symbol = item.get("symbol")
                price = item.get("current_price")

                try:
                    signals = process_symbol_signals(item)
                    success_hits = update_success_targets(symbol, price)

                    for s in success_hits:
                        push_success_signal(s)
                        send_telegram_message(
                            format_signal_message(s)
                        )

                    for s in signals:
                        push_signal(s)
                        send_telegram_message(
                            format_signal_message(s)
                        )

                except Exception as e:
                    print(f"⚠ {symbol} hata:", e, flush=True)

        except Exception as e:
            print("🔥 Scanner genel hata:", e, flush=True)

        # ==================================================
        # HAFTALIK RAPOR (CUMA 18:10+ / 1 KERE)
        # ==================================================
        if now.weekday() == 4 and now.time() >= dtime(18, 10):
            week_id = now.strftime("%Y-%W")
            if last_weekly_report != week_id:
                report = build_weekly_success_report()
                if report:
                    send_telegram_message(report)
                last_weekly_report = week_id

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
