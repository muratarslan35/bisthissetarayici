import json
import os
from datetime import datetime, timezone
import yfinance as yf
from utils import FALLBACK_SYMBOLS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "fallback_state.json")

NO_MOVE_DAYS_LIMIT = 3
MIN_DAILY_RANGE_PCT = 0.3

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def has_daily_movement(symbol):
    try:
        df = yf.download(symbol, period="5d", interval="1d", auto_adjust=True, progress=False)
        if df is None or len(df) < 2:
            return False
        last = df.iloc[-1]
        rng_pct = ((last["High"] - last["Low"])/last["Close"])*100
        return rng_pct >= MIN_DAILY_RANGE_PCT
    except:
        return False

def fallback_daily_update_if_needed(symbols_list):
    state = load_state()
    updated = False
    for sym in FALLBACK_SYMBOLS:
        moved = has_daily_movement(sym)
        st = state.get(sym, {"no_move_days":0,"last_check":datetime.now(timezone.utc).date().isoformat()})
        if moved:
            st["no_move_days"]=0
        else:
            st["no_move_days"]+=1
        state[sym]=st
        if st["no_move_days"]>=NO_MOVE_DAYS_LIMIT:
            updated=True
    save_state(state)
    return updated

def fallback_daily_report_message():
    state = load_state()
    removed = [k for k,v in state.items() if v.get("no_move_days",0)>=NO_MOVE_DAYS_LIMIT]
    if not removed:
        return None
    return "📌 Fallback Listesi Güncellendi:\n" + "\n".join(removed)
