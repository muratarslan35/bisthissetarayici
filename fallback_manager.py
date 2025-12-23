import json
import os
from datetime import datetime, timedelta, timezone
import yfinance as yf

from utils import FALLBACK_SYMBOLS

# ==================================================
# AYARLAR
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")

NO_MOVE_DAYS_LIMIT = 3
MIN_DAILY_RANGE_PCT = 0.3  # %0.3 altı = hareketsiz kabul

# ==================================================
# STATE LOAD / SAVE
# ==================================================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ==================================================
# GÜNLÜK HAREKET KONTROLÜ
# ==================================================
def has_daily_movement(symbol):
    try:
        df = yf.download(
            symbol,
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False
        )
        if df is None or len(df) < 2:
            return False

        last = df.iloc[-1]
        rng_pct = ((last["High"] - last["Low"]) / last["Close"]) * 100
        return rng_pct >= MIN_DAILY_RANGE_PCT

    except Exception:
        return False

# ==================================================
# FALLBACK LİSTEYİ GÜNCELLE
# ==================================================
def update_fallback_list(candidate_symbols=None):
    """
    candidate_symbols:
      - yeni eklenmesi düşünülen semboller (opsiyonel)
    """

    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()

    removed = []
    kept = []
    added = []

    current_list = FALLBACK_SYMBOLS.copy()

    # -----------------------------
    # MEVCUT FALLBACK KONTROLÜ
    # -----------------------------
    for sym in current_list:
        moved = has_daily_movement(sym)

        sym_state = state.get(sym, {
            "no_move_days": 0,
            "last_check": today
        })

        if moved:
            sym_state["no_move_days"] = 0
            kept.append(sym)
        else:
            sym_state["no_move_days"] += 1
            if sym_state["no_move_days"] >= NO_MOVE_DAYS_LIMIT:
                removed.append(sym)
            else:
                kept.append(sym)

        sym_state["last_check"] = today
        state[sym] = sym_state

    # -----------------------------
    # YENİ ADAY EKLEME
    # -----------------------------
    if candidate_symbols:
        for sym in candidate_symbols:
            if sym in kept or sym in removed:
                continue

            if has_daily_movement(sym):
                kept.append(sym)
                added.append(sym)
                state[sym] = {
                    "no_move_days": 0,
                    "last_check": today
                }

    save_state(state)

    return {
        "kept": kept,
        "removed": removed,
        "added": added
    }
