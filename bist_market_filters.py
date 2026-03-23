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
    try:
        return code.strip().upper().replace(".IS", "") + ".IS"
    except:
        return None


def parse_date_safe(date_str):
    try:
        return parser.parse(date_str).date()
    except:
        return None


def days_left_calc(dt):
    try:
        if not dt:
            return None
        return (dt - datetime.now().date()).days
    except:
        return None


# ======================================================
# 1️⃣ VBTS API (structured)
# ======================================================

def fetch_vbts():

    url = "https://www.kap.org.tr/tr/api/vbts"

    results = {}

    try:

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            print("⚠ VBTS status:", r.status_code)
            return results

        data = r.json()

        if not isinstance(data, list):
            return results

        for item in data:

            try:

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

                symbol = normalize_symbol(code)
                if not symbol:
                    continue

                end_dt = parse_date_safe(end_date)
                days_left = days_left_calc(end_dt)

                if days_left is not None and days_left < 0:
                    continue

                results[symbol] = {
                    "end_date": str(end_dt),
                    "days_left": days_left,
                    "source": "VBTS"
                }

            except Exception as e:
                print("VBTS item hata:", e)
                continue

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

        r = requests.get(url, headers=HEADERS, timeout=12)

        if r.status_code != 200:
            print("⚠ DISCLOSURE status:", r.status_code)
            return results

        data = r.json()

        if not isinstance(data, list):
            return results

        for item in data[:300]:

            try:

                title = str(item.get("title","")).upper()

                if "BRÜT" not in title and "BRUT" not in title:
                    continue

                codes = item.get("stockCodes")

                if not codes:
                    continue

                symbol = normalize_symbol(codes.split(",")[0])

                if not symbol:
                    continue

                results[symbol] = {
                    "end_date": None,
                    "days_left": None,
                    "source": "DISCLOSURE",
                    "title": title
                }

            except Exception as e:
                print("DISC item hata:", e)
                continue

    except Exception as e:
        print("⚠ DISCLOSURE FAIL:", e)
        return {}  # 🔥 KRİTİK → sistem devam eder

    return results


# ======================================================
# 3️⃣ HTML + REGEX (backup)
# ======================================================

def fetch_regex():

    url = "https://www.kap.org.tr/tr/BistTedbirleri"

    results = {}

    try:

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            print("⚠ REGEX status:", r.status_code)
            return results

        matches = re.findall(
            r'([A-Z]{3,5})\s*</td>\s*<td>.*?</td>\s*<td>.*?</td>\s*<td>(\d{2}\.\d{2}\.\d{4})',
            r.text
        )

        for sym, end_date in matches:

            try:

                symbol = normalize_symbol(sym)
                if not symbol:
                    continue

                end_dt = parse_date_safe(end_date)
                days_left = days_left_calc(end_dt)

                if days_left is not None and days_left < 0:
                    continue

                results[symbol] = {
                    "end_date": end_date,
                    "days_left": days_left,
                    "source": "REGEX"
                }

            except Exception as e:
                print("REGEX item hata:", e)
                continue

    except Exception as e:
        print("⚠ REGEX FAIL:", e)

    return results


# ======================================================
# 🔥 MAIN ENGINE (ULTRA SAFE)
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    try:

        now = datetime.now()

        # CACHE
        if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
            return BRUT_CACHE

        final = {}

        # --------------------------------------------------
        # VBTS
        # --------------------------------------------------
        try:
            vbts = fetch_vbts()
            if isinstance(vbts, dict):
                final.update(vbts)
        except Exception as e:
            print("VBTS merge hata:", e)

        # --------------------------------------------------
        # DISCLOSURE
        # --------------------------------------------------
        try:
            disc = fetch_disclosures()
            if isinstance(disc, dict):
                for k, v in disc.items():
                    final.setdefault(k, v)
        except Exception as e:
            print("DISC merge hata:", e)

        # --------------------------------------------------
        # REGEX
        # --------------------------------------------------
        try:
            regex = fetch_regex()
            if isinstance(regex, dict):
                for k, v in regex.items():
                    final.setdefault(k, v)
        except Exception as e:
            print("REGEX merge hata:", e)

        # --------------------------------------------------
        # VALIDATION
        # --------------------------------------------------

        clean = {}

        for k, v in final.items():

            try:

                if not isinstance(k, str):
                    continue

                if not k.endswith(".IS"):
                    continue

                if not isinstance(v, dict):
                    continue

                if v.get("days_left") is not None:

                    if v["days_left"] < 0:
                        continue

                    if v["days_left"] > 90:
                        continue

                clean[k] = v

            except Exception as e:
                print("VALIDATION hata:", e)
                continue

        # --------------------------------------------------

        BRUT_CACHE = clean
        LAST_UPDATE = now

        print(f"📊 BRÜT TAKAS SAYISI: {len(clean)}")

        return clean

    except Exception as e:

        print("🔥 get_brut_list KRİTİK HATA:", e)

        # 🔥 EN ÖNEMLİ KISIM → SİSTEM ASLA DURMAZ
        return BRUT_CACHE if BRUT_CACHE else {}
