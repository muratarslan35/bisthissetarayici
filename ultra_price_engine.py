import time
import threading
import json
import os
import requests

from volume_engine import update_tick

# ======================================================
# CONFIG (ULTRA PRO)
# ======================================================

BATCH_SIZE = 40          # 🔥 tek requestte 40 hisse
FETCH_INTERVAL = 2       # kaç saniyede bir fetch

STALE_TTL = 6
SAVE_INTERVAL = 15

MAX_KEEP_SECONDS = 300
CLEANUP_INTERVAL = 30

CACHE_FILE = "data/price_cache.json"

# ======================================================
# GLOBAL
# ======================================================

PRICE_CACHE = {}
LAST_UPDATE = {}

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

                if now - ts < MAX_KEEP_SECONDS:
                    PRICE_CACHE[k] = v.get("price")
                    LAST_UPDATE[k] = ts

        print(f"💾 CACHE LOADED: {len(PRICE_CACHE)}")

    except Exception as e:
        print("cache load error:", e)

# ======================================================
# CACHE SAVE
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
# CLEANUP
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

        if to_delete:
            print(f"🧹 CLEANUP: {len(to_delete)} symbol silindi")

        time.sleep(CLEANUP_INTERVAL)

# ======================================================
# 🔥 TRADINGVIEW SCANNER (TEK GERÇEK KAYNAK)
# ======================================================

def fetch_batch(symbols):
    try:
        url = "https://scanner.tradingview.com/turkey/scan"

        tv_symbols = [
            f"BIST:{s.replace('.IS','')}"
            for s in symbols
        ]

        payload = {
            "symbols": {
                "tickers": tv_symbols,
                "query": {"types": []}
            },
            "columns": ["close"]
        }

        r = requests.post(url, json=payload, timeout=6)

        data = r.json()

        result = {}

        if "data" in data:
            for item in data["data"]:
                tv_symbol = item["s"]          # BIST:THYAO
                price = item["d"][0]

                clean = tv_symbol.replace("BIST:", "") + ".IS"

                if price:
                    result[clean] = float(price)

        return result

    except Exception as e:
        print("❌ BATCH FETCH ERROR:", e)
        return {}

# ======================================================
# WORKER (BATCH MODE)
# ======================================================

class BatchWorker(threading.Thread):
    def __init__(self, symbols):
        super().__init__(daemon=True)
        self.symbols = symbols

    def run(self):
        while RUNNING:

            batch_prices = fetch_batch(self.symbols)

            now = time.time()

            if batch_prices:

                with LOCK:
                    for symbol, price in batch_prices.items():
                        PRICE_CACHE[symbol] = price
                        LAST_UPDATE[symbol] = now

                        update_tick(symbol, price)

            else:
                print("⚠ batch boş döndü")

            time.sleep(FETCH_INTERVAL)

# ======================================================
# START
# ======================================================

def start_engine(symbols):

    load_cache()

    # 🔥 batch böl
    chunks = [
        symbols[i:i + BATCH_SIZE]
        for i in range(0, len(symbols), BATCH_SIZE)
    ]

    for ch in chunks:
        BatchWorker(ch).start()

    threading.Thread(target=save_cache, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    print(f"🚀 BATCH ENGINE STARTED | batch={len(chunks)}")

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
