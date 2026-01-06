from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

from signal_engine import build_weekly_success_report, week_key

dashboard_bp = Blueprint("dashboard", __name__)

TR_TZ = ZoneInfo("Europe/Istanbul")

SIGNALS = []
SUCCESS_SIGNALS = []

MAX_SIGNALS = 200
MAX_SUCCESS_SIGNALS = 50

RESET_TIME = dtime(9, 40)
LAST_DASHBOARD_RESET_DATE = None

# ======================================================
# RESET
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
# PUSH
# ======================================================

def push_signal(signal):
    SIGNALS.insert(0, signal)
    del SIGNALS[MAX_SIGNALS:]


def push_success_signal(signal):
    SUCCESS_SIGNALS.insert(0, signal)
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

    weekly_text = build_weekly_success_report()

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),
        "signals": SUCCESS_SIGNALS + SIGNALS,
        "weekly_report": {
            "week_id": week_key(),
            "text": weekly_text
        } if weekly_text else None
    })
