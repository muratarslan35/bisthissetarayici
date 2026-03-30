import time
import threading
import json
import os
import requests
import random
import re

from volume_engine import update_tick

# ======================================================
# CONFIG (FINAL STABLE)
# ======================================================

BATCH_SIZE = 8          # düşük tut → ban yeme
FETCH_INTERVAL = 5       # agresif olma

STALE_TTL = 10
SAVE_INTERVAL = 15

MAX_KEEP_SECONDS = 300
CLEANUP_INTERVAL = 30

CACHE_FILE = "data/price_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# ======================================================
# GLOBAL
# ======================================================

PRICE_CACHE = {}
LAST_UPDATE = {}

LOCK = threading.Lock()
RUNNING = True

TV_FAIL_COUNT = 0

# ======================================================
# CACHE
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
                if now - ts < MAX_KEEP_SECONDS:
                    PRICE_CACHE[k] = v.get("price")
                    LAST_UPDATE[k] = ts

        print(f"💾 CACHE LOADED: {len(PRICE_CACHE)}")

    except Exception as e:
        print("cache load error:", e)

def save_cache():
    while RUNNING:
        try:
            os.makedirs("data", exist_ok=True)

            now = time.time()

            with LOCK:
                data = {
                    k: {"price": v, "ts": LAST_UPDATE.get(k, now)}
                    for k, v in PRICE_CACHE.items()
                    if now - LAST_UPDATE.get(k, 0) < MAX_KEEP_SECONDS
                }

            with open(CACHE_FILE, "w") as f:
                json.dump(data, f)

        except Exception as e:
            print("cache save error:", e)

        time.sleep(SAVE_INTERVAL)

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

        time.sleep(CLEANUP_INTERVAL)

# ======================================================
# 🔥 TRADINGVIEW (PRIMARY)
# ======================================================

def fetch_batch(symbols):
    global TV_FAIL_COUNT

    try:
        url = "https://scanner.tradingview.com/turkey/scan"

        tv_symbols = [f"BIST:{s.replace('.IS','')}" for s in symbols]

        payload = {
            "symbols": {
                "tickers": tv_symbols,
                "query": {"types": []}
            },
            "columns": ["close"]
        }

        r = requests.post(url, json=payload, headers=HEADERS, timeout=6)

        text = r.text.strip()

        if not text or text.startswith("<"):
            TV_FAIL_COUNT += 1
            print("⚠ TV BLOCK")
            return {}

        data = r.json()

        result = {}

        for item in data.get("data", []):
            try:
                symbol = item["s"].replace("BIST:", "") + ".IS"
                price = item["d"][0]

                if price:
                    result[symbol] = float(price)

            except:
                continue

        if result:
            TV_FAIL_COUNT = 0

        return result

    except Exception as e:
        TV_FAIL_COUNT += 1
        print("❌ TV ERROR:", e)
        return {}

# ======================================================
# 🔥 INVESTING (FALLBACK)
# ======================================================

def fetch_investing(symbol):
    try:
        clean = symbol.replace(".IS", "").lower()

        url = f"https://www.investing.com/equities/{clean}-stock"

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        r = requests.get(url, headers=headers, timeout=5)

        if r.status_code != 200:
            return None

        m = re.search(r'"last"\s*:\s*([\d.]+)', r.text)

        if m:
            return float(m.group(1))

    except:
        return None

# ======================================================
# WORKER
# ======================================================

class Worker(threading.Thread):
    def __init__(self, symbols):
        super().__init__(daemon=True)
        self.symbols = symbols

    def run(self):
        global TV_FAIL_COUNT

        while RUNNING:

            # 🔥 PRIMARY
            if TV_FAIL_COUNT < 2:
                prices = fetch_batch(self.symbols)
            else:
                prices = {}

            now = time.time()

            if prices:
                with LOCK:
                    for s, p in prices.items():
                        PRICE_CACHE[s] = p
                        LAST_UPDATE[s] = now
                        update_tick(s, p)

            else:
                print("⚠ FALLBACK MODE")

                for s in self.symbols:
                    p = fetch_investing(s)

                    if p:
                        with LOCK:
                            PRICE_CACHE[s] = p
                            LAST_UPDATE[s] = now
                            update_tick(s, p)

                    time.sleep(random.uniform(0.1, 0.2))

            time.sleep(FETCH_INTERVAL + random.uniform(0.5, 1.5))

# ======================================================
# START
# ======================================================

def start_engine(symbols):

    load_cache()

    chunks = [
        symbols[i:i + BATCH_SIZE]
        for i in range(0, len(symbols), BATCH_SIZE)
    ]

    # 🔥 MAX 4 WORKER
    chunks = chunks[:2]

    for ch in chunks:
        Worker(ch).start()

    threading.Thread(target=save_cache, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    print(f"🚀 FINAL ENGINE STARTED | workers={len(chunks)}")

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
