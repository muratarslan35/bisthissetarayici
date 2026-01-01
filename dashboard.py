from flask import Blueprint, jsonify
from datetime import datetime, time
from zoneinfo import ZoneInfo

dashboard_bp = Blueprint("dashboard", __name__)

TR_TZ = ZoneInfo("Europe/Istanbul")

SIGNALS = []
SUCCESS_SIGNALS = []

MAX_SIGNALS = 200
MAX_SUCCESS_SIGNALS = 50

# ======================================================
# PUSH FUNCTIONS
# ======================================================

def get_nearest_resistance(levels):
    if not levels:
        return None
    return max(l["level"] for l in levels)

def push_signal(signal):
    category = "strong"
    if signal["action"] == "GÜÇLENEN SİNYAL":
        category = "strengthened"
    if "KOMBİNE" in signal["main_algorithm"]:
        category = "combo"

    res_1h = None
    res_4h = None
    if "tf" in signal:
        if "1h" in signal["tf"]:
            res_1h = get_nearest_resistance(signal["tf"]["1h"].get("nearest_levels"))
        if "4h" in signal["tf"]:
            res_4h = get_nearest_resistance(signal["tf"]["4h"].get("nearest_levels"))

    SIGNALS.insert(0, {
        "symbol": signal["symbol"],
        "price": signal["price"],
        "ema_trend": signal["ema_trend"],
        "algorithms": [signal["main_algorithm"]] + signal.get("helpers", []),
        "res_1h": res_1h,
        "res_4h": res_4h,
        "time": signal["time"],
        "title": signal["action"],
        "category": category
    })
    del SIGNALS[MAX_SIGNALS:]

def push_success_signal(data):
    SUCCESS_SIGNALS.insert(0, {
        "symbol": data["symbol"],
        "algorithm": data["algorithm"],
        "time": data["time"],
        "category": "success",
        "title": "🎯 %1.5 HEDEF"
    })
    del SUCCESS_SIGNALS[MAX_SUCCESS_SIGNALS:]

# ======================================================
# MARKET STATUS
# ======================================================

def is_market_open(now=None):
    """
    BIST saatlerine göre piyasa açık/kapalı
    Pazartesi-Cuma 09:40-18:05
    """
    now = now or datetime.now(TR_TZ)
    if now.weekday() >= 5:  # Cumartesi & Pazar
        return False

    start = time(9, 40)
    end = time(18, 5)
    return start <= now.time() <= end

# ======================================================
# API
# ======================================================

@dashboard_bp.route("/api/dashboard")
def dashboard_api():
    now = datetime.now(TR_TZ)
    market_open = is_market_open(now)
    system_active = True  # Tarama sistemi her zaman aktif

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),
        "signals": SUCCESS_SIGNALS + SIGNALS
    })
