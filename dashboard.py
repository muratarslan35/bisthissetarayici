from flask import Blueprint, jsonify, current_app
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests

# signal_engine verileri
from signal_engine import (
    build_weekly_success_report,
    week_key,load_weekly_state,
    WEEKLY_SUCCESS_TRACKER,
    FRIDAY_CLOSE_PRICES,
    DAILY_SUCCESS_TRACKER,
    today_key
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

    # ❗ SADECE GÜNLÜK GÖRÜNÜMÜ TEMİZLE
    SIGNALS.clear()
    SUCCESS_SIGNALS.clear()

    # ❌ WEEKLY_SUCCESS_TRACKER'a ASLA DOKUNMA
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
# WEEKLY TABLE DATA
# ======================================================

TR_DAYS = {
    "Monday": "Pazartesi",
    "Tuesday": "Salı",
    "Wednesday": "Çarşamba",
    "Thursday": "Perşembe",
    "Friday": "Cuma"
}

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

        friday_price = FRIDAY_CLOSE_PRICES.get(symbol)
        sell_price = d.get("hit_price")  # hedef geldiğinde

        current_price = (
            sell_price if isinstance(sell_price, (int, float))
            else friday_price if isinstance(friday_price, (int, float))
            else None
        )

        entry_day_raw = d.get("entry_day")
        entry_day = TR_DAYS.get(entry_day_raw, entry_day_raw)

        hit_day_raw = d.get("hit_day")
        hit_day = TR_DAYS.get(hit_day_raw, hit_day_raw)

        sell_gain_pct = None
        live_gain_pct = None

        if isinstance(entry, (int, float)):
            if isinstance(sell_price, (int, float)):
                sell_gain_pct = round(((sell_price - entry) / entry) * 100, 2)

            if isinstance(current_price, (int, float)):
                live_gain_pct = round(((current_price - entry) / entry) * 100, 2)

        # ⏱ SÜRE
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
                    else f"{duration_minutes//60}s {duration_minutes%60}dk"
                )
            except Exception:
                pass

        row = {
            "symbol": symbol,
            "algorithm": algo,

            "entry_price": round(entry, 2) if isinstance(entry, (int, float)) else None,
            "current_price": round(current_price, 2) if isinstance(current_price, (int, float)) else None,

            "sell_price": round(sell_price, 2) if isinstance(sell_price, (int, float)) else None,
            "sell_gain_pct": sell_gain_pct,
            "live_gain_pct": live_gain_pct,
            "gain_pct": sell_gain_pct,  # frontend uyumu

            "entry_day": entry_day,
            "hit_day": hit_day,
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

    summary = {
        "total": len(week_data),
        "success": len(success),
        "failed": len(failed),
    }

    return {
        "success": success,
        "failed": failed,
        "summary": summary,
    }

# ======================================================
# LIVE GAIN % (HER API ÇAĞRISINDA HESAPLANIR)
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

        s = dict(s)
        s["live_gain_pct"] = live_gain_pct
        enriched.append(s)

    return enriched

# ======================================================
# API
# ======================================================

@dashboard_bp.route("/api/dashboard")
def dashboard_api():
    now = datetime.now(TR_TZ)

    # 🔑 WEEKLY RAM BOŞSA DISKTEN YÜKLE
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

    # ==================================================
    # 🔥 GÜNLÜK BAŞARILI SİNYALLER
    # ==================================================
    daily_success = []
    t_key = today_key()

    for d in DAILY_SUCCESS_TRACKER.get(t_key, {}).values():
        if not d.get("hit"):
            continue

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
                    diff += 24 * 60
                duration_minutes = int(diff)
                if duration_minutes < 60:
                    duration_label = f"{duration_minutes} dk"
                else:
                    duration_label = f"{duration_minutes//60}s {duration_minutes%60}dk"
            except Exception:
                pass

        daily_success.append({
            "symbol": d.get("symbol"),
            "price": d.get("hit_price"),
            "entry_price": d.get("entry"),
            "category": "success",
            "action": "BAŞARILI",
            "main_algorithm": d.get("algo"),
            "time": d.get("hit_time"),
            "helpers": d.get("helpers", []),
            "title": "🎯 HEDEF GELDİ",
            "entry_time": entry_time,
            "hit_time": hit_time,
            "duration_minutes": duration_minutes,
            "duration_label": duration_label,
        })

    weekly_text = build_weekly_success_report()

    all_signals = daily_success + SUCCESS_SIGNALS + SIGNALS

    return jsonify({
        "market_open": market_open,
        "system_active": system_active,
        "server_time": now.strftime("%H:%M:%S"),

        # ✅ CANLI % HER SEFERİNDE YENİDEN HESAPLANIR
        "signals": enrich_live_gain(all_signals),

        "weekly_report": {
            "week_id": week_key(),
            "text": weekly_text
        } if weekly_text else None,

        "weekly_table": build_weekly_table_data()
    })
