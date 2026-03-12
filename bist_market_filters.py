import requests
from datetime import datetime

# ======================================================
# CACHE
# ======================================================

BRUT_CACHE = {}
HALT_CACHE = set()

LAST_BRUT_UPDATE = None
LAST_HALT_UPDATE = None


# ======================================================
# BRÜT TAKAS LİSTESİ
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_BRUT_UPDATE

    now = datetime.now()

    # günde 1 kez çek
    if LAST_BRUT_UPDATE and (now - LAST_BRUT_UPDATE).days == 0:
        return BRUT_CACHE

    brut_map = {}

    try:

        url = "https://www.kap.org.tr/tr/api/trading-halts"

        r = requests.get(url, timeout=10)

        if r.status_code == 200:

            data = r.json()

            for item in data:

                code = item.get("stockCode")

                if not code:
                    continue

                symbol = code + ".IS"

                end_date = item.get("endDate")

                days_left = None

                if end_date:
                    try:
                        end_dt = datetime.strptime(end_date[:10], "%Y-%m-%d")
                        days_left = (end_dt - now).days
                    except:
                        pass

                brut_map[symbol] = {
                    "end_date": end_date,
                    "days_left": days_left
                }

    except Exception as e:
        print(f"⚠ BRÜT TAKAS ÇEKİLEMEDİ → {e}")

    BRUT_CACHE = brut_map
    LAST_BRUT_UPDATE = now

    print(f"📊 BRÜT TAKAS SAYISI: {len(brut_map)}")

    return brut_map


# ======================================================
# DEVRE KESİCİ / HALT LİSTESİ
# ======================================================

def get_halt_list():

    global HALT_CACHE, LAST_HALT_UPDATE

    now = datetime.now()

    # 5 dakikada bir çek
    if LAST_HALT_UPDATE and (now - LAST_HALT_UPDATE).seconds < 300:
        return HALT_CACHE

    halt_set = set()

    try:

        url = "https://www.kap.org.tr/tr/api/trading-halts"

        r = requests.get(url, timeout=10)

        if r.status_code == 200:

            data = r.json()

            for item in data:

                code = item.get("stockCode")

                if code:
                    halt_set.add(code + ".IS")

    except Exception as e:

        print(f"⚠ HALT LİSTESİ ÇEKİLEMEDİ → {e}")

    HALT_CACHE = halt_set
    LAST_HALT_UPDATE = now

    return halt_set
