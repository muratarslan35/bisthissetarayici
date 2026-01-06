from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

# ✅ signal_engine'den haftalık rapor
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
        "entry_price": signal.get("entry_price"),

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

        # ✅ GÜÇ
        "power": signal.get("power"),
        "power_delta": signal.get("power_delta"),

        # ✅ MOST (YENİ SİSTEM)
        "most_1h": signal.get("most_1h"),
        "most_4h": signal.get("most_4h"),
    })

    del SIGNALS[MAX_SIGNALS:]


def push_success_signal(signal):
    """
    signal_engine -> update_success_targets çıktısı
    """
    SUCCESS_SIGNALS.insert(0, {
        "symbol": signal.get("symbol"),
        "price": signal.get("price"),
        "entry_price": signal.get("entry_price"),

        "ema_trend": None,
        "volume_ok": None,

        "helpers_detail": [],
        "helpers": signal.get("helpers", []),

        "history": signal.get("history", []),

        "resistance_1h": None,
        "resistance_4h": None,

        "time": signal.get("time"),
        "title": signal.get("title", "🎯 HEDEF GELDİ"),
        "action": "BAŞARILI",
        "category": "success",
        "main_algorithm": signal.get("main_algorithm"),

        "power": None,
        "power_delta": None,

        "gain_pct": signal.get("gain_pct"),

        "most_1h": None,
        "most_4h": None,
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

    # ==================================================
    # WEEKLY REPORT (DASHBOARD)
    # ==================================================
    weekly_report_text = build_weekly_success_report()
    weekly_report = None

    if weekly_report_text:
        weekly_report = {
            "week_id": week_key(),
            "text": weekly_report_text
        }

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),

        # dashboard kartları
        "signals": SUCCESS_SIGNALS + SIGNALS,

        # haftalık analiz sekmesi
        "weekly_report": weekly_report
    })
