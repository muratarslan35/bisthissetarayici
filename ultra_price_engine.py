import time
import threading
import json
import os
import requests

from volume_engine import update_tick

# ======================================================
# CONFIG (PRO STABLE)
# ======================================================

BATCH_SIZE = 25
FETCH_INTERVAL = 3

STALE_TTL = 8
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
                    k: {"price": v, "ts": LAST_UPDATE.get(k, now)}
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
            print(f"🧹 CLEANUP: {len(to_delete)} silindi")

        time.sleep(CLEANUP_INTERVAL)

# ======================================================
# 🔥 YAHOO FALLBACK (KRİTİK)
# ======================================================

def fetch_yahoo(symbol):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")

        if hist.empty:
            return None

        return float(hist["Close"].iloc[-1])
    except:
        return None

# ======================================================
# 🔥 TRADINGVIEW BATCH (SAFE)
# ======================================================

def fetch_batch(symbols):
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

        # 🔥 BLOCK / HTML / EMPTY CHECK
        if not text or text.startswith("<"):
            print("⚠ TV BLOCK / EMPTY RESPONSE")
            return {}

        data = r.json()

        result = {}

        for item in data.get("data", []):
            try:
                tv_symbol = item["s"]
                price = item["d"][0]

                if not price:
                    continue

                clean = tv_symbol.replace("BIST:", "") + ".IS"
                result[clean] = float(price)

            except:
                continue

        return result

    except Exception as e:
        print("❌ BATCH ERROR:", e)
        return {}

# ======================================================
# WORKER
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
                print("⚠ batch fail → fallback devrede")

                # 🔥 FALLBACK MODE
                for s in self.symbols:
                    price = fetch_yahoo(s)
                    if price:
                        with LOCK:
                            PRICE_CACHE[s] = price
                            LAST_UPDATE[s] = now
                            update_tick(s, price)

                    time.sleep(0.2)

            time.sleep(FETCH_INTERVAL)

# ======================================================
# START
# ======================================================

def start_engine(symbols):

    load_cache()

    chunks = [
        symbols[i:i + BATCH_SIZE]
        for i in range(0, len(symbols), BATCH_SIZE)
    ]

    for ch in chunks:
        BatchWorker(ch).start()

    threading.Thread(target=save_cache, daemon=True).start()
    threading.Thread(target=cleanup_loop, daemon=True).start()

    print(f"🚀 ENGINE STARTED | batch={len(chunks)}")

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
