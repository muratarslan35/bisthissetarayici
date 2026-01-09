from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

# signal_engine verileri
from signal_engine import (
    build_weekly_success_report,
    week_key,
    WEEKLY_SUCCESS_TRACKER,
    FRIDAY_CLOSE_PRICES
)

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
# WEEKLY TABLE DATA (YENİ + GÜVENLİ)
# ======================================================

TR_DAYS = {
    "Monday": "Pazartesi",
    "Tuesday": "Salı",
    "Wednesday": "Çarşamba",
    "Thursday": "Perşembe",
    "Friday": "Cuma"
}

def build_weekly_table_data():
    """
    Dashboard haftalık tablo verisi üretir
    - Başarılı
    - Başarısız
    - Özet
    """
    w_key = week_key()
    week_data = WEEKLY_SUCCESS_TRACKER.get(w_key, {})

    success = []
    failed = []

    for d in week_data.values():
        symbol = d.get("symbol")
        entry = d.get("entry")
        algo = d.get("algo")
        helpers = d.get("helpers", [])

        friday_price = FRIDAY_CLOSE_PRICES.get(symbol)
        current_price = d.get("hit_price") or friday_price

        # ---------- GÜVENLİK FIX #1 ----------
        entry_day_raw = d.get("entry_day")
        entry_day = (
            TR_DAYS.get(entry_day_raw, entry_day_raw)
            if entry_day_raw else None
        )

        hit_day_raw = d.get("hit_day")
        hit_day = (
            TR_DAYS.get(hit_day_raw, hit_day_raw)
            if hit_day_raw else None
        )

        # ---------- GÜVENLİK FIX #2 ----------
        gain_pct = None
        if isinstance(current_price, (int, float)) and isinstance(entry, (int, float)):
            gain_pct = round(((current_price - entry) / entry) * 100, 2)

        row = {
            "symbol": symbol,
            "algorithm": algo,
            "entry_price": round(entry, 2) if isinstance(entry, (int, float)) else None,
            "current_price": round(current_price, 2)
                if isinstance(current_price, (int, float))
                else None,
            "entry_day": entry_day,
            "hit_day": hit_day,
            "gain_pct": gain_pct,
            "helpers": helpers,
            "entry_date": str(d.get("entry_date")) if d.get("entry_date") else None,
            "hit_time": d.get("hit_time"),
        }

        if d.get("hit"):
            success.append(row)
        else:
            failed.append(row)

    summary = {
        "total": len(week_data),
        "success": len(success),
        "failed": len(failed)
    }

    return {
        "success": success,
        "failed": failed,
        "summary": summary
    }

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

        # Günlük + başarılı sinyaller
        "signals": SUCCESS_SIGNALS + SIGNALS,

        # Haftalık metin raporu
        "weekly_report": {
            "week_id": week_key(),
            "text": weekly_text
        } if weekly_text else None,

        # Haftalık tablo (dashboard için)
        "weekly_table": build_weekly_table_data()
    })
