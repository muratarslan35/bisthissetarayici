from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

from signal_engine import (
    build_weekly_success_report,
    week_key,
    load_weekly_state,
    WEEKLY_SUCCESS_TRACKER,
    FRIDAY_CLOSE_PRICES,
    DAILY_SUCCESS_TRACKER,
    REENTRY_DAILY_TRACKER,
    today_key,
)

dashboard_bp = Blueprint("dashboard", __name__)

TR_TZ = ZoneInfo("Europe/Istanbul")

# ======================================================
# IN-MEMORY STATE
# ======================================================

SIGNALS = []
SUCCESS_SIGNALS = []

MAX_SIGNALS = 200
MAX_SUCCESS_SIGNALS = 50

RESET_TIME = dtime(9, 40)
LAST_DASHBOARD_RESET_DATE = None


# ======================================================
# RESET MEKANİZMASI
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
# PUSH HELPERS
# ======================================================

def push_signal(signal):
    SIGNALS.insert(0, signal)
    del SIGNALS[MAX_SIGNALS:]


def push_success_signal(signal):
    SUCCESS_SIGNALS.insert(0, signal)
    del SUCCESS_SIGNALS[MAX_SUCCESS_SIGNALS:]


# ======================================================
# GÜN İSİMLERİ
# ======================================================

TR_DAYS = {
    "Monday": "Pazartesi",
    "Tuesday": "Salı",
    "Wednesday": "Çarşamba",
    "Thursday": "Perşembe",
    "Friday": "Cuma",
}


# ======================================================
# WEEKLY TABLE DATA
# ======================================================

def build_weekly_table_data():
    w_key = week_key()
    week_data = WEEKLY_SUCCESS_TRACKER.get(w_key, {})

    success = []
    failed = []

    for d in week_data.values():
        symbol = d.get("symbol")
        algo = d.get("algo")
        entry = d.get("entry")
        helpers = d.get("helpers", [])

        sell_price = d.get("hit_price")
        current_price = FRIDAY_CLOSE_PRICES.get(symbol)

        sell_gain_pct = None
        live_gain_pct = None

        if isinstance(entry, (int, float)):
            if isinstance(sell_price, (int, float)):
                sell_gain_pct = round(((sell_price - entry) / entry) * 100, 2)

            if isinstance(current_price, (int, float)):
                live_gain_pct = round(((current_price - entry) / entry) * 100, 2)

        entry_day_raw = d.get("entry_day")
        entry_day = TR_DAYS.get(entry_day_raw, entry_day_raw)

        entry_time = d.get("entry_time")
        hit_time = d.get("hit_time")

        duration_minutes = None
        duration_label = None

        if entry_time and hit_time:
            try:
                et = datetime.strptime(entry_time, "%H:%M:%S")
                ht = datetime.strptime(hit_time, "%H:%M:%S")
                diff = (ht - et).total_seconds() / 60
                if diff < 0:
                    diff += 1440
                duration_minutes = int(diff)
                duration_label = (
                    f"{duration_minutes} dk"
                    if duration_minutes < 60
                    else f"{duration_minutes // 60}s {duration_minutes % 60}dk"
                )
            except Exception:
                pass

        row = {
            "symbol": symbol,
            "algorithm": algo,
            "signal_type": d.get("signal_type", "primary"),
            "reentry": d.get("signal_type") == "reentry",
            "entry_price": round(entry, 2) if isinstance(entry, (int, float)) else None,
            "current_price": round(current_price, 2) if isinstance(current_price, (int, float)) else None,
            "sell_price": round(sell_price, 2) if isinstance(sell_price, (int, float)) else None,
            "sell_gain_pct": sell_gain_pct,
            "live_gain_pct": live_gain_pct,
            "gain_pct": gain_pct,
            "entry_day": entry_day,
            "entry_time": entry_time,
            "hit_time": hit_time,
            "duration_minutes": duration_minutes,
            "duration_label": duration_label,
            "helpers": helpers,
        }

        if d.get("hit"):
            success.append(row)
        else:
            failed.append(row)

    return {
        "success": success,
        "failed": failed,
        "summary": {
            "total": len(week_data),
            "success": len(success),
            "failed": len(failed),
        },
    }


# ======================================================
# LIVE GAIN ENRICH
# ======================================================

def enrich_live_gain(signals):
    enriched = []

    for s in signals:
        entry = s.get("entry_price")
        price = s.get("price")

        live_gain_pct = None
        if isinstance(entry, (int, float)) and isinstance(price, (int, float)):
            try:
                live_gain_pct = round(((price - entry) / entry) * 100, 2)
            except Exception:
                pass

        s2 = dict(s)
        s2["live_gain_pct"] = live_gain_pct
        enriched.append(s2)

    return enriched


# ======================================================
# API
# ======================================================

@dashboard_bp.route("/api/dashboard")
def dashboard_api():
    now = datetime.now(TR_TZ)

    if not WEEKLY_SUCCESS_TRACKER:
        weekly, friday = load_weekly_state()
        WEEKLY_SUCCESS_TRACKER.update(weekly)
        FRIDAY_CLOSE_PRICES.update(friday)

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

    # ======================================================
    # DAILY SUCCESS
    # ======================================================

    daily_success = []
    t_key = today_key()

    for d in DAILY_SUCCESS_TRACKER.get(t_key, {}).values():
        if not d.get("hit"):
            continue

        entry = d.get("entry")
        hit_price = d.get("hit_price")

        gain_pct = None
        if entry is not None and hit_price is not None and entry != 0:
            gain_pct = round(((hit_price - entry) / entry) * 100, 2)

        daily_success.append({
            "symbol": d.get("symbol"),
            "price": hit_price,
            "entry_price": entry,
            "category": "success",
            "action": "BAŞARILI",
            "main_algorithm": d.get("algo"),
            "time": d.get("hit_time"),
            "helpers": d.get("helpers", []),
            "helpers_detail": [],
            "power_delta": 0,
            "signal_type": d.get("signal_type", "primary"),
            "reentry": d.get("signal_type") == "reentry",
            "title": "🎯 HEDEF GELDİ (RE-ENTRY)" if d.get("signal_type") == "reentry" else "🎯 HEDEF GELDİ",
            "gain_pct": gain_pct,
        })

    # ======================================================
    # ♻️ RE-ENTRY DAILY TABLE
    # ======================================================

    reentry_daily = []

    for r in REENTRY_DAILY_TRACKER.get(t_key, {}).values():
        if not r.get("hit"):
            continue

        gain_pct = round(((r["hit_price"] - r["entry"]) / r["entry"]) * 100, 2)

        reentry_daily.append({
            "symbol": r["symbol"],
            "algo": r["algo"],
            "entry_price": r["entry"],
            "hit_price": r["hit_price"],
            "gain_pct": gain_pct,
            "time": r["hit_time"],
        })

    weekly_text = build_weekly_success_report()

    all_signals = daily_success + SUCCESS_SIGNALS + SIGNALS

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),
        "signals": enrich_live_gain(all_signals),
        "weekly_report": {
            "week_id": week_key(),
            "text": weekly_text,
        } if weekly_text else None,
        "weekly_table": build_weekly_table_data(),
        "reentry_daily": reentry_daily,
    })
