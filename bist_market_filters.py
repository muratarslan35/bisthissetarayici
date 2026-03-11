import requests
from bs4 import BeautifulSoup
from datetime import datetime


BRUT_CACHE = {}
HALT_CACHE = {}

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

    url = "https://www.kap.org.tr/tr/BistTedbirleri"

    brut_map = {}

    try:

        r = requests.get(url, timeout=10)

        soup = BeautifulSoup(r.text, "html.parser")

        tables = soup.find_all("table")

        for table in tables:

            rows = table.find_all("tr")

            for row in rows:

                cols = row.find_all("td")

                if len(cols) < 4:
                    continue

                try:

                    symbol = cols[0].text.strip().split(".")[0] + ".IS"

                    end_date_text = cols[3].text.strip()

                    end_date = datetime.strptime(end_date_text, "%d.%m.%Y")

                    days_left = (end_date - now).days

                    brut_map[symbol] = {
                        "end_date": end_date_text,
                        "days_left": days_left
                    }

                except:
                    continue

    except Exception as e:

        print(f"⚠ BRÜT TAKAS ÇEKİLEMEDİ → {e}")

    BRUT_CACHE = brut_map
    LAST_BRUT_UPDATE = now

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
