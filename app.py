import time
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template
import yfinance as yf

from utils import (
    FALLBACK_SYMBOLS,
    fetch_tradingview_price,
    fetch_bist_fallback,
    build_timeframes,
    to_tr_timezone,
    send_telegram_message
)

from signal_engine import (
    process_signals,
    format_signal_message,
    update_success
)

app = Flask(__name__, template_folder="templates", static_folder="static")

SCAN_INTERVAL = 60
signals_cache = []
last_scan_time = None
bot_running = True


def fetch_symbol_data(symbol):
    price = fetch_tradingview_price(symbol)
    if not price:
        price = fetch_bist_fallback(symbol)
    if not price:
        return None

    try:
        df_5m = yf.download(symbol, period="5d", interval="5m", progress=False)
        df_15m = yf.download(symbol, period="10d", interval="15m", progress=False)
        df_1h = yf.download(symbol, period="30d", interval="1h", progress=False)
        df_4h = yf.download(symbol, period="60d", interval="4h", progress=False)
    except Exception:
        return None

    if df_15m.empty or df_5m.empty:
        return None

    tf = build_timeframes(
        df_5m=df_5m,
        df_15m=df_15m,
        df_1h=df_1h,
        df_4h=df_4h
    )

    return {
        "symbol": symbol,
        "current_price": float(price),
        "tf": tf
    }


def scan_loop():
    global signals_cache, last_scan_time

    send_telegram_message("🤖 BIST BOT BAŞLATILDI")

    while bot_running:
        all_signals = []
        scanned = 0

        for symbol in FALLBACK_SYMBOLS:
            data = fetch_symbol_data(symbol)
            if not data:
                continue

            scanned += 1
            update_success(symbol, data["current_price"])

            signals = process_signals(data)
            if signals:
                for s in signals:
                    msg = format_signal_message(s)
                    send_telegram_message(msg)
                all_signals.extend(signals)

        signals_cache = sorted(
            all_signals,
            key=lambda x: x["strength"],
            reverse=True
        )

        last_scan_time = to_tr_timezone(datetime.now(timezone.utc))

        time.sleep(SCAN_INTERVAL)


@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        signals=signals_cache,
        last_update=last_scan_time.strftime("%H:%M:%S") if last_scan_time else "-"
    )


@app.route("/api")
def api_signals():
    return jsonify({
        "last_update": last_scan_time.strftime("%H:%M:%S") if last_scan_time else None,
        "count": len(signals_cache),
        "signals": signals_cache
    })


def start_bot():
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    start_bot()
    app.run(host="0.0.0.0", port=5000, debug=False)
