from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

dashboard_bp = Blueprint("dashboard", __name__)

TR_TZ = ZoneInfo("Europe/Istanbul")

SIGNALS = []
SUCCESS_SIGNALS = []

MAX_SIGNALS = 200
MAX_SUCCESS_SIGNALS = 50

RESET_TIME = dtime(9, 40)
LAST_DASHBOARD_RESET_DATE = None

# ======================================================
# RESET CONTROL
# ======================================================

def reset_dashboard_if_needed(now):
    global LAST_DASHBOARD_RESET_DATE

    if now.time() < RESET_TIME:
        return

    if LAST_DASHBOARD_RESET_DATE == now.date():
        return

    SIGNALS.clear()
    SUCCESS_SIGNALS.clear()
    LAST_DASHBOARD_RESET_DATE = now.date()

# ======================================================
# PUSH FUNCTIONS
# ======================================================

def push_signal(signal):
    SIGNALS.insert(0, {
        "symbol": signal.get("symbol"),
        "price": signal.get("price"),
        "ema_trend": signal.get("ema_trend"),
        "volume_ok": signal.get("volume_ok"),
        "helpers_detail": signal.get("helpers_detail"),
        "helpers": signal.get("helpers"),
        "history": signal.get("history"),
        "resistance_1h": signal.get("resistance_1h"),
        "resistance_4h": signal.get("resistance_4h"),
        "time": signal.get("time"),
        "title": signal.get("title"),
        "action": signal.get("action"),
        "category": signal.get("category"),
        "main_algorithm": signal.get("main_algorithm"),

        # ✅ EKLENENLER
        "power": signal.get("power"),
        "power_delta": signal.get("power_delta"),
        "most_state": signal.get("most_state"),
    })

    del SIGNALS[MAX_SIGNALS:]


def push_success_signal(data):
    SUCCESS_SIGNALS.insert(0, {
        "symbol": data.get("symbol"),
        "price": None,
        "ema_trend": None,
        "volume_ok": None,
        "helpers_detail": [],
        "helpers": [],
        "history": [],
        "resistance_1h": None,
        "resistance_4h": None,
        "time": data.get("time"),
        "title": "🎯 %1.5 HEDEF GELDİ",
        "action": "BAŞARILI",
        "category": "success",
        "main_algorithm": data.get("algorithm"),
        "power": None,
        "power_delta": None,
        "most_state": None,
    })

    del SUCCESS_SIGNALS[MAX_SUCCESS_SIGNALS:]

# ======================================================
# API
# ======================================================

@dashboard_bp.route("/api/dashboard")
def dashboard_api():
    now = datetime.now(TR_TZ)

    reset_dashboard_if_needed(now)

    market_open = False
    system_active = False

    try:
        health_url = current_app.config.get(
            "SELF_URL", "http://127.0.0.1:5000"
        ) + "/health"

        r = requests.get(health_url, timeout=2)
        if r.status_code == 200:
            h = r.json()
            market_open = h.get("market_open", False)
            system_active = True
    except Exception:
        pass

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),
        "signals": SUCCESS_SIGNALS + SIGNALS
    })
