import requests
import re
import time
from datetime import datetime
from dateutil import parser

HEADERS = {"User-Agent": "Mozilla/5.0"}

CACHE_TTL = 60

BRUT_CACHE = {}
LAST_UPDATE = None


# ======================================================
# SAFE HELPERS
# ======================================================

def normalize_symbol(code):
    return code.strip().upper().replace(".IS", "") + ".IS"


def parse_date_safe(date_str):
    try:
        return parser.parse(date_str).date()
    except:
        return None


def days_left_calc(dt):
    if not dt:
        return None
    return (dt - datetime.now().date()).days


# ======================================================
# 1️⃣ VBTS API (structured)
# ======================================================

def fetch_vbts():

    url = "https://www.kap.org.tr/tr/api/vbts"

    results = {}

    try:

        r = requests.get(url, headers=HEADERS, timeout=8)

        if r.status_code != 200:
            return results

        data = r.json()

        for item in data:

            text = (
                str(item.get("title","")) +
                str(item.get("decisionText","")) +
                str(item)
            ).upper()

            if "BRÜT" not in text and "BRUT" not in text:
                continue

            code = item.get("stockCode")
            end_date = item.get("endDate")

            if not code:
                continue

            end_dt = parse_date_safe(end_date)
            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[normalize_symbol(code)] = {
                "end_date": str(end_dt),
                "days_left": days_left,
                "source": "VBTS"
            }

    except Exception as e:
        print("⚠ VBTS FAIL:", e)

    return results


# ======================================================
# 2️⃣ DISCLOSURE API (EN KRİTİK)
# ======================================================

def fetch_disclosures():

    url = "https://www.kap.org.tr/tr/api/disclosures"

    results = {}

    try:

        r = requests.get(url, headers=HEADERS, timeout=8)

        if r.status_code != 200:
            return results

        data = r.json()

        for item in data[:200]:

            title = str(item.get("title","")).upper()

            if "BRÜT" not in title and "BRUT" not in title:
                continue

            codes = item.get("stockCodes")

            if not codes:
                continue

            symbol = normalize_symbol(codes.split(",")[0])

            results[symbol] = {
                "end_date": None,
                "days_left": None,
                "source": "DISCLOSURE",
                "title": title
            }

    except Exception as e:
        print("⚠ DISCLOSURE FAIL:", e)

    return results


# ======================================================
# 3️⃣ HTML + REGEX (backup)
# ======================================================

def fetch_regex():

    url = "https://www.kap.org.tr/tr/BistTedbirleri"

    results = {}

    try:

        r = requests.get(url, headers=HEADERS, timeout=8)

        matches = re.findall(
            r'([A-Z]{3,5})\s*</td>\s*<td>.*?</td>\s*<td>.*?</td>\s*<td>(\d{2}\.\d{2}\.\d{4})',
            r.text
        )

        for sym, end_date in matches:

            end_dt = parse_date_safe(end_date)
            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[normalize_symbol(sym)] = {
                "end_date": end_date,
                "days_left": days_left,
                "source": "REGEX"
            }

    except Exception as e:
        print("⚠ REGEX FAIL:", e)

    return results


# ======================================================
# 🔥 MAIN ENGINE
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
        return BRUT_CACHE

    final = {}

    # 1️⃣ VBTS
    vbts = fetch_vbts()
    final.update(vbts)

    # 2️⃣ DISCLOSURE (kritik)
    disc = fetch_disclosures()
    for k, v in disc.items():
        final.setdefault(k, v)

    # 3️⃣ REGEX (her zaman çalışır)
    regex = fetch_regex()
    for k, v in regex.items():
        final.setdefault(k, v)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    clean = {}

    for k, v in final.items():

        if not k.endswith(".IS"):
            continue

        # brute kesin veri yoksa bile dahil et (disclosure)
        if v.get("days_left") is not None:

            if v["days_left"] < 0:
                continue

            if v["days_left"] > 90:
                continue

        clean[k] = v

    # --------------------------------------------------

    BRUT_CACHE = clean
    LAST_UPDATE = now

    print(f"📊 BRÜT TAKAS SAYISI: {len(clean)}")

    return clean
