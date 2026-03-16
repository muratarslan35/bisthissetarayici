import requests
from datetime import datetime
from dateutil import parser
from bs4 import BeautifulSoup

# ======================================================
# CACHE
# ======================================================

BRUT_CACHE = {}
HALT_CACHE = set()

LAST_BRUT_UPDATE = None
LAST_HALT_UPDATE = None

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


# ======================================================
# BRÜT TAKAS LİSTESİ
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_BRUT_UPDATE

    now = datetime.now()

    # cache (günde 1 kez)
    if LAST_BRUT_UPDATE and (now - LAST_BRUT_UPDATE).days == 0:
        return BRUT_CACHE

    brut_map = {}

    # ======================================================
    # 1️⃣ BIST VBTS API (ANA KAYNAK)
    # ======================================================

    try:

        url = "https://www.kap.org.tr/tr/api/vbts"

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:

            data = r.json()

            for item in data:

                text = str(item).upper()

                if "BRÜT" not in text and "BRUT" not in text:
                    continue

                code = item.get("stockCode")

                end_date = item.get("endDate")

                if not code or not end_date:
                    continue

                try:

                    end_dt = parser.parse(end_date).date()

                    days_left = (end_dt - now.date()).days

                    if days_left < 0:
                        continue

                except:
                    continue

                brut_map[code + ".IS"] = {
                    "end_date": end_date,
                    "days_left": days_left
                }

    except Exception as e:

        print("⚠ VBTS API okunamadı:", e)

    # ======================================================
    # 2️⃣ KAP HALT API (İKİNCİ KAYNAK)
    # ======================================================

    try:

        url = "https://www.kap.org.tr/tr/api/trading-halts"

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:

            data = r.json()

            for item in data:

                code = item.get("stockCode")

                end_date = item.get("endDate")

                if not code or not end_date:
                    continue

                try:

                    end_dt = parser.parse(end_date).date()

                    days_left = (end_dt - now.date()).days

                    if days_left < 0:
                        continue

                except:
                    continue

                brut_map.setdefault(code + ".IS", {
                    "end_date": end_date,
                    "days_left": days_left
                })

    except Exception as e:

        print("⚠ HALT API okunamadı:", e)

    # ======================================================
    # 3️⃣ KAP WEB FALLBACK
    # ======================================================

    if len(brut_map) == 0:

        try:

            url = "https://www.kap.org.tr/tr/BistTedbirleri"

            r = requests.get(url, headers=HEADERS, timeout=10)

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

                        end_dt = parser.parse(end_date_text).date()

                        days_left = (end_dt - now.date()).days

                        if days_left < 0:
                            continue

                        brut_map[symbol] = {
                            "end_date": end_date_text,
                            "days_left": days_left
                        }

                    except:
                        continue

        except Exception as e:

            print("⚠ KAP WEB fallback hatası:", e)

    # ======================================================
    # CACHE
    # ======================================================

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

    # cache 5 dakika
    if LAST_HALT_UPDATE and (now - LAST_HALT_UPDATE).seconds < 300:
        return HALT_CACHE

    halt_set = set()

    try:

        url = "https://www.kap.org.tr/tr/api/trading-halts"

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code == 200:

            data = r.json()

            for item in data:

                code = item.get("stockCode")

                if code:
                    halt_set.add(code + ".IS")

    except Exception as e:

        print("⚠ HALT LISTESI OKUNAMADI:", e)

    HALT_CACHE = halt_set
    LAST_HALT_UPDATE = now

    return halt_set
