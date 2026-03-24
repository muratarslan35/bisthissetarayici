import requests
import re
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
# VBTS
# ======================================================

def fetch_vbts():

    url = "https://www.kap.org.tr/tr/api/vbts"
    results = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return results

        data = r.json()

        for item in data:

            text = (str(item) or "").upper()

            if "BRÜT" not in text and "BRUT" not in text:
                continue

            code = item.get("stockCode")
            if not code:
                continue

            symbol = normalize_symbol(code)

            end_dt = parse_date_safe(item.get("endDate"))
            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[symbol] = {
                "days_left": days_left
            }

    except Exception as e:
        print("VBTS error:", e)

    return results


# ======================================================
# DISCLOSURE
# ======================================================

def fetch_disclosures():

    url = "https://www.kap.org.tr/tr/api/disclosures"
    results = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return results

        data = r.json()

        for item in data[:300]:

            title = str(item.get("title","")).upper()

            if "BRÜT" not in title and "BRUT" not in title:
                continue

            codes = item.get("stockCodes")

            if not codes:
                continue

            symbol = normalize_symbol(codes.split(",")[0])

            results[symbol] = {
                "days_left": None
            }

    except Exception as e:
        print("DISC error:", e)

    return results


# ======================================================
# REGEX
# ======================================================

def fetch_regex():

    url = "https://www.kap.org.tr/tr/BistTedbirleri"
    results = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)

        matches = re.findall(
            r'([A-Z]{3,5}).*?(\d{2}\.\d{2}\.\d{4})',
            r.text
        )

        for sym, date_str in matches:

            symbol = normalize_symbol(sym)

            end_dt = parse_date_safe(date_str)
            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[symbol] = {
                "days_left": days_left
            }

    except Exception as e:
        print("REGEX error:", e)

    return results


# ======================================================
# MAIN
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
        return BRUT_CACHE

    final = {}

    final.update(fetch_vbts())
    final.update(fetch_disclosures())
    final.update(fetch_regex())

    clean = {}

    for k, v in final.items():

        if not k or not k.endswith(".IS"):
            continue

        clean[k] = v

    BRUT_CACHE = clean
    LAST_UPDATE = now

    print(f"📊 BRÜT: {len(clean)}")

    return clean


# ======================================================
# 🔥 HALT DETECTOR (EDGE)
# ======================================================

def detect_halt_from_data(item):

    try:

        tf15 = item.get("tf", {}).get("15m")
        if not tf15:
            return False

        df = tf15.get("df")

        if df is None or len(df) < 5:
            return False

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if last["Close"] == prev["Close"]:

            vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

            if vol_ma and last["Volume"] < vol_ma * 0.1:
                return True

        spread = (last["High"] - last["Low"]) / last["Close"]

        if spread > 0.05:
            return True

        return False

    except:
        return False


# fallback
def get_halt_list():
    return set()
