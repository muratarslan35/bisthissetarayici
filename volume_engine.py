import time
from collections import defaultdict, deque
from threading import Lock

# ======================================================
# CONFIG
# ======================================================

WINDOW_SECONDS = 60
MAX_TICKS = 500

# ======================================================
# GLOBAL
# ======================================================

TICKS = defaultdict(lambda: deque(maxlen=MAX_TICKS))
LAST_PRICE = {}
LOCK = Lock()

# ======================================================
# UPDATE TICK (ULTRA PRICE ENGINE BURAYI BESLER)
# ======================================================

def update_tick(symbol, price):

    now = time.time()

    with LOCK:

        prev = LAST_PRICE.get(symbol)

        if prev is None:
            LAST_PRICE[symbol] = price
            return

        # price değişmişse tick say
        if price != prev:

            TICKS[symbol].append({
                "price": price,
                "ts": now
            })

            LAST_PRICE[symbol] = price

# ======================================================
# REAL-TIME VOLUME (TICK BASED)
# ======================================================

def get_tick_volume(symbol):

    now = time.time()

    with LOCK:

        ticks = TICKS.get(symbol, [])

        recent = [
            t for t in ticks
            if now - t["ts"] <= WINDOW_SECONDS
        ]

        return len(recent)

# ======================================================
# RVOL (SMART)
# ======================================================

def get_rvol(symbol):

    with LOCK:

        ticks = list(TICKS.get(symbol, []))

    if len(ticks) < 20:
        return 0

    now = time.time()

    recent = [t for t in ticks if now - t["ts"] <= 60]
    older = [t for t in ticks if 60 < now - t["ts"] <= 180]

    if not older:
        return 0

    return len(recent) / max(len(older), 1)

# ======================================================
# VOLUME SPIKE
# ======================================================

def detect_volume_spike(symbol):

    rvol = get_rvol(symbol)

    if rvol >= 2:
        return True

    return False
