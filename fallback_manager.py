import json
import os
from datetime import datetime, timedelta

STATE_FILE = "fallback_state.json"

MAX_INACTIVE_DAYS = 3     # veri yoksa
MAX_NO_MOVE_DAYS = 5     # mum var ama hareket yoksa

def _load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def ensure_symbol(symbol):
    state = _load_state()
    if symbol not in state:
        state[symbol] = {
            "inactive_days": 0,
            "no_move_days": 0,
            "passive": False,
            "last_seen": None
        }
        _save_state(state)

def report_success(symbol):
    state = _load_state()
    ensure_symbol(symbol)
    state[symbol]["inactive_days"] = 0
    state[symbol]["no_move_days"] = 0
    state[symbol]["passive"] = False
    state[symbol]["last_seen"] = datetime.now().strftime("%Y-%m-%d")
    _save_state(state)

def report_no_data(symbol):
    state = _load_state()
    ensure_symbol(symbol)
    state[symbol]["inactive_days"] += 1
    if state[symbol]["inactive_days"] >= MAX_INACTIVE_DAYS:
        state[symbol]["passive"] = True
    _save_state(state)

def report_no_movement(symbol):
    state = _load_state()
    ensure_symbol(symbol)
    state[symbol]["no_move_days"] += 1
    if state[symbol]["no_move_days"] >= MAX_NO_MOVE_DAYS:
        state[symbol]["passive"] = True
    _save_state(state)

def get_active_symbols():
    state = _load_state()
    return [s for s, v in state.items() if not v.get("passive", False)]
