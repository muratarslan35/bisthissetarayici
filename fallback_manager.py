import json
import os
from datetime import datetime, timezone
import yfinance as yf

from utils import FALLBACK_SYMBOLS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")
NO_MOVE_DAYS_LIMIT = 3
MIN_DAILY_RANGE_PCT = 0.3  # %0.3 altı = hareketsiz kabul

# ------------------ STATE ------------------
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

# ------------------ HAREKET KONTROL ------------------
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

# ------------------ GÜNCELLE ------------------
def fallback_daily_update_if_needed(data_list=None):
    """
    Her gün bir kez fallback listesini günceller.
    data_list opsiyonel, fetch_bist_data çıktısı.
    """
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()
    updated = False

    current_list = FALLBACK_SYMBOLS.copy()

    for sym in current_list:
        moved = has_daily_movement(sym)
        sym_state = state.get(sym, {"no_move_days": 0, "last_check": today})

        if moved:
            sym_state["no_move_days"] = 0
        else:
            sym_state["no_move_days"] += 1
            if sym_state["no_move_days"] >= NO_MOVE_DAYS_LIMIT:
                updated = True  # listeden çıkarılacak
        sym_state["last_check"] = today
        state[sym] = sym_state

    save_state(state)
    return updated

# ------------------ RAPOR ------------------
def fallback_daily_report_message():
    """
    Hareket etmeyen sembolleri raporlar.
    """
    state = load_state()
    removed = [s for s, v in state.items() if v.get("no_move_days", 0) >= NO_MOVE_DAYS_LIMIT]
    if removed:
        msg = "📌 Hareketsiz hisseler (fallback listeden çıkarılabilir):\n" + "\n".join(removed)
        return msg
    return None
