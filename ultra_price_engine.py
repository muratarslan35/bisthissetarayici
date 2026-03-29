import time
import random
import threading
import json
import os

from volume_engine import update_tick

# ======================================================
# CONFIG (ORACLE SAFE)
# ======================================================

MAX_WORKERS = 6
BATCH_SIZE = 8

MIN_DELAY = 0.08
MAX_DELAY = 0.25

CACHE_TTL = 1.5
STALE_TTL = 6

SAVE_INTERVAL = 10

# 🔥 CLEANUP CONFIG
MAX_KEEP_SECONDS = 300      # RAM + disk max tutma süresi (5 dk)
CLEANUP_INTERVAL = 30

CACHE_FILE = "data/price_cache.json"

# ======================================================
# GLOBAL
# ======================================================

PRICE_CACHE = {}
LAST_UPDATE = {}
FAIL_COUNT = {}

LOCK = threading.Lock()
RUNNING = True

# ======================================================
# CACHE LOAD
# ======================================================

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)

        now = time.time()

        with LOCK:
            for k, v in data.items():
                ts = v.get("ts", 0)

                # 🔥 sadece fresh olanları yükle
                if now - ts < MAX_KEEP_SECONDS:
                    PRICE_CACHE[k] = v.get("price")
                    LAST_UPDATE[k] = ts

        print(f"💾 CACHE LOADED: {len(PRICE_CACHE)}")

    except Exception as e:
        print("cache load error:", e)

# ======================================================
# CACHE SAVE (STALE CLEAN)
# ======================================================

def save_cache():
    while RUNNING:
        try:
            os.makedirs("data", exist_ok=True)

            now = time.time()

            with LOCK:
                data = {
                    k: {
                        "price": v,
                        "ts": LAST_UPDATE.get(k, now)
                    }
                    for k, v in PRICE_CACHE.items()
                    if now - LAST_UPDATE.get(k, 0) < MAX_KEEP_SECONDS
                }

            with open(CACHE_FILE, "w") as f:
                json.dump(data, f)

        except Exception as e:
            print("cache save error:", e)

        time.sleep(SAVE_INTERVAL)

# ======================================================
# 🔥 RAM CLEANUP LOOP
# ======================================================

def cleanup_loop():

    while RUNNING:

        now = time.time()

        with LOCK:
            to_delete = [
                k for k, ts in LAST_UPDATE.items()
                if now - ts > MAX_KEEP_SECONDS
            ]

            for k in to_delete:
                PRICE_CACHE.pop(k, None)
                LAST_UPDATE.pop(k, None)
                FAIL_COUNT.pop(k, None)

        if to_delete:
            print(f"🧹 CLEANUP: {len(to_delete)} symbol silindi")

        time.sleep(CLEANUP_INTERVAL)

# ======================================================
# PRIMARY SOURCE
# ======================================================

def fetch_primary(symbol):
    from utils import fetch_tradingview_price
    return fetch_tradingview_price(symbol)

# ======================================================
# FALLBACK
# ======================================================

def fetch_fallback(symbol):
    try:
        import requests, re

        url = f"https://www.investing.com/equities/{symbol.replace('.IS','').lower()}"
        r = requests.get(url, timeout=5)

        if r.status_code != 200:
            return None

        m = re.search(r'"last"\s*:\s*([\d.]+)', r.text)
        if m:
            return float(m.group(1))

    except:
        return None

# ======================================================
# SMART FETCH
# ======================================================

def smart_fetch(symbol):

    # CACHE
    with LOCK:
        ts = LAST_UPDATE.get(symbol, 0)
        if time.time() - ts < CACHE_TTL:
            return PRICE_CACHE.get(symbol)

    # PRIMARY
    price = fetch_primary(symbol)

    if price:
        with LOCK:
            PRICE_CACHE[symbol] = price
            LAST_UPDATE[symbol] = time.time()
            FAIL_COUNT[symbol] = 0

        update_tick(symbol, price)
        return price

    # FALLBACK
    price = fetch_fallback(symbol)

    if price:
        with LOCK:
            PRICE_CACHE[symbol] = price
            LAST_UPDATE[symbol] = time.time()
            FAIL_COUNT[symbol] = 0

        update_tick(symbol, price)
        return price

    # FAIL
    with LOCK:
        FAIL_COUNT[symbol] = FAIL_COUNT.get(symbol, 0) + 1

    return None

# ======================================================
# DELAY (AUTO THROTTLE)
# ======================================================

def dynamic_delay(symbol):
    fails = FAIL_COUNT.get(symbol, 0)

    if fails > 5:
        return random.uniform(0.3, 0.6)
    elif fails > 2:
        return random.uniform(0.15, 0.35)
    else:
        return random.uniform(MIN_DELAY, MAX_DELAY)

# ======================================================
# WORKER
# ======================================================

class Worker(threading.Thread):
    def __init__(self, symbols):
        super().__init__(daemon=True)
        self.symbols = symbols

    def run(self):
        while RUNNING:
            for s in self.symbols:
                try:
                    smart_fetch(s)
                except:
                    pass

                time.sleep(dynamic_delay(s))

# ======================================================
# START
# ======================================================

def start_engine(symbols):

    load_cache()

    chunks = [
        symbols[i:i + BATCH_SIZE]
        for i in range(0, len(symbols), BATCH_SIZE)
    ]

    chunks = chunks[:MAX_WORKERS]

    for ch in chunks:
        Worker(ch).start()

    threading.Thread(target=save_cache, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    print(f"🚀 ENGINE STARTED | workers={len(chunks)}")

# ======================================================
# READ
# ======================================================

def get_price(symbol):

    with LOCK:
        price = PRICE_CACHE.get(symbol)
        ts = LAST_UPDATE.get(symbol, 0)

    if time.time() - ts < STALE_TTL:
        return price

    return None
