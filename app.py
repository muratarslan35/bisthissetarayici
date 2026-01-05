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
    tr_now,

    # ✅ YENİ EKLENENLER
    reset_daily_success_if_needed,
    reset_weekly_success_if_needed,
    send_weekly_report_if_needed
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
        print("⚠ Telegram kapalı", flush=True)
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
            print("⚠ Telegram hata:", e, flush=True)

# ======================================================
# STARTUP
# ======================================================
def send_startup_message():
    msg = (
        "🟢 <b>BIST TARAMA SİSTEMİ BAŞLATILDI</b>\n\n"
        f"🕒 {now_tr().strftime('%H:%M:%S')} | {now_tr().strftime('%d.%m.%Y')}\n"
        "📡 Scanner aktif"
    )
    send_telegram_message(msg)

# ======================================================
# DAILY REPORT (MEVCUT – KORUNDU)
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
# SIGNAL REPEAT CONTROL (MEVCUT – KORUNDU)
# ======================================================
LAST_SENT_SIGNAL = {}

def is_duplicate_signal(signal):
    key = (
        signal["symbol"],
        signal["main_algorithm"],
        signal["action"]
    )

    prev = LAST_SENT_SIGNAL.get(key)

    current_power = signal.get("power", 0)
    current_most = signal.get("most_state")

    if prev:
        if prev.get("most_state") != current_most:
            pass
        elif current_power <= prev.get("power", 0):
            return True

    LAST_SENT_SIGNAL[key] = {
        "power": current_power,
        "most_state": current_most,
        "time": signal.get("time")
    }
    return False

# ======================================================
# SCANNER LOOP
# ======================================================
def scanner_loop():
    send_startup_message()
    last_report_day = None

    while True:
        now = now_tr()
        print(f"\n⏱ Döngü tick: {now.strftime('%H:%M:%S')}", flush=True)

        # ==================================================
        # ✅ GÜNLÜK / HAFTALIK RESET & RAPOR
        # ==================================================
        reset_daily_success_if_needed()
        reset_weekly_success_if_needed()
        send_weekly_report_if_needed(send_telegram_message)

        try:
            if not is_market_open(now):
                print("⏹ Market kapalı – beklemede", flush=True)

                if last_report_day != now.date() and now.time() > BIST_CLOSE:
                    send_daily_success_report()
                    last_report_day = now.date()

                time.sleep(30)
                continue

            print("✅ MARKET AÇIK → TARAMA BAŞLIYOR", flush=True)

            try:
                market_data = fetch_bist_data()
            except Exception as e:
                print("🔥 fetch_bist_data çökmesi:", e, flush=True)
                time.sleep(5)
                continue

            print(f"📈 Taranan hisse: {len(market_data)}", flush=True)

            for item in market_data:
                symbol = item.get("symbol")

                try:
                    signals = process_symbol_signals(item)
                    successes = update_success_targets(
                        symbol, item["current_price"]
                    )

                    for s in successes:
                        push_success_signal(s)
                        send_telegram_message(
                            format_signal_message(s)
                        )

                    for signal in signals:
                        if is_duplicate_signal(signal):
                            continue

                        push_signal(signal)
                        send_telegram_message(
                            format_signal_message(signal)
                        )

                except Exception as e:
                    print(f"⚠ {symbol} işlenirken hata:", e, flush=True)

        except Exception as e:
            print("🔥 Scanner genel hata:", e, flush=True)

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
