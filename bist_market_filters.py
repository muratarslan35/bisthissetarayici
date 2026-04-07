import requests
from datetime import datetime
from dateutil import parser

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "tr-TR,tr;q=0.9"
}

CACHE_TTL = 120

BRUT_CACHE = {}
LAST_UPDATE = None


# ======================================================
# HELPERS
# ======================================================

def normalize_symbol(code):
    try:
        return code.strip().upper().replace(".IS", "") + ".IS"
    except:
        return None


def parse_date_safe(date_str):
    try:
        if not date_str:
            return None
        return parser.parse(date_str, dayfirst=True).date()
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
# 🔥 API (ANA KAYNAK - EN SAĞLAM)
# ======================================================

def fetch_vbts():

    url = "https://www.kap.org.tr/tr/api/vbts"
    results = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            print("❌ VBTS HTTP ERROR:", r.status_code)
            return results

        data = r.json()

        for item in data:

            # sadece brüt olanları al
            tedbir = str(item.get("measureType", "")).upper()
            if "BRÜT" not in tedbir and "BRUT" not in tedbir:
                continue

            code = item.get("stockCode")
            if not code:
                continue

            symbol = normalize_symbol(code)

            start_dt = parse_date_safe(item.get("startDate"))
            end_dt = parse_date_safe(item.get("endDate"))

            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[symbol] = {
                "start_date": str(start_dt) if start_dt else "-",
                "end_date": str(end_dt) if end_dt else "-",
                "days_left": days_left,
                "type": tedbir or "Brüt Takas"
            }

        print(f"📡 API BRÜT: {len(results)}")

    except Exception as e:
        print("❌ VBTS ERROR:", e)

    return results


# ======================================================
# 🔥 FALLBACK SCRAPER (SADECE YEDEK)
# ======================================================

def fetch_scrape_backup():

    url = "https://www.kap.org.tr/tr/BistTedbirleri"
    results = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            return results

        html = r.text

        # daha geniş regex
        import re
        matches = re.findall(
            r'([A-Z]{3,5})\s+.*?(\d{2}\.\d{2}\.\d{4})',
            html
        )

        for sym, date_str in matches:

            symbol = normalize_symbol(sym)
            end_dt = parse_date_safe(date_str)
            days_left = days_left_calc(end_dt)

            if days_left is not None and days_left < 0:
                continue

            results[symbol] = {
                "start_date": "-",
                "end_date": str(end_dt),
                "days_left": days_left,
                "type": "Brüt Takas"
            }

        print(f"📡 SCRAPE BACKUP: {len(results)}")

    except Exception as e:
        print("SCRAPE ERROR:", e)

    return results


# ======================================================
# 🔥 MAIN
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    # cache
    if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
        return BRUT_CACHE

    final = {}

    # 🔥 1. API (ANA)
    api_data = fetch_vbts()
    final.update(api_data)

    # 🔥 2. backup scrape
    if len(final) == 0:
        print("⚠ API boş → scrape deneniyor")
        scrape_data = fetch_scrape_backup()
        final.update(scrape_data)

    # temizle
    clean = {}

    for k, v in final.items():
        if not k or not k.endswith(".IS"):
            continue
        clean[k] = v

    # fallback cache
    if not clean:
        print("⚠ BRÜT BOŞ → CACHE")
        return BRUT_CACHE

    BRUT_CACHE = clean
    LAST_UPDATE = now

    print(f"✅ BRÜT TOPLAM: {len(clean)}")

    return clean
