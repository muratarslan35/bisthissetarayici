import os, time, threading, requests
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory
from fetch_bist import fetch_bist_data
from utils import to_tr_timezone

app = Flask(__name__)

LATEST_DATA = []
LAST_SCAN_TS = 0
SYSTEM_STARTED = False
data_lock = threading.Lock()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_IDS = [int(x) for x in os.getenv("CHAT_IDS","").split(",") if x]

def telegram_send(msg):
    if not TELEGRAM_TOKEN: return
    for cid in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=5
            )
        except:
            pass

def market_open():
    now = to_tr_timezone(datetime.now(timezone.utc))
    return now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 55)) and now.hour < 18

def background_loop():
    global LATEST_DATA, LAST_SCAN_TS, SYSTEM_STARTED
    SYSTEM_STARTED = True
    telegram_send("🤖 Sistem aktif – Oracle VM")

    while True:
        try:
            data = fetch_bist_data()
            with data_lock:
                LATEST_DATA = data
                LAST_SCAN_TS = int(time.time())

            # 📊 MARKET KAPALI ÖZET
            if not market_open():
                strong = [x["symbol"] for x in data if x.get("super_combined_ok")]
                if strong:
                    telegram_send(
                        "📊 PİYASA KAPALI – SON GÜÇLÜ HİSSELER\n\n" +
                        "\n".join(f"• {s}" for s in strong[:5])
                    )

        except Exception as e:
            print("SCAN ERROR:", e)

        time.sleep(60)

threading.Thread(target=background_loop, daemon=True).start()

@app.route("/api")
def api():
    with data_lock:
        return jsonify({
            "system_active": int(SYSTEM_STARTED),
            "market_open": int(market_open()),
            "last_scan": LAST_SCAN_TS,
            "data": LATEST_DATA
        })

@app.route("/wake")
def wake():
    return jsonify({"ok":1})

@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
