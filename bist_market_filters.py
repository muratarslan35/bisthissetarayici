import requests
import re
from datetime import datetime
from dateutil import parser
import feedparser
import json
import os

# 🔥 GEMINI AI
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def gemini_parse_brut(text):

    try:

        if not GEMINI_API_KEY:
            return {}

        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""
Aşağıdaki metinden brüt takas uygulanan hisseleri çıkar.

Sadece JSON dön:

[
  {{
    "symbol": "XXX.IS"
  }}
]

Metin:
{text}
"""

        response = model.generate_content(prompt)

        raw = response.text.strip()

        data = json.loads(raw)

        results = {}

        for item in data:
            sym = item.get("symbol")
            if sym:
                results[sym] = {
                    "start_date": "-",
                    "end_date": "-",
                    "days_left": None,
                    "type": "Brüt Takas (AI)",
                    "priority": 80
                }

        return results

    except Exception as e:
        print("GEMINI ERROR:", e)
        return {}

# ======================================================
# CONFIG
# ======================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "tr-TR,tr;q=0.9"
}

CACHE_TTL = 300

BRUT_CACHE = {}
LAST_UPDATE = None

MANUAL_FILE = "data/manual_brut.json"

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
# MANUAL OVERRIDE
# ======================================================

def load_manual():
    if not os.path.exists(MANUAL_FILE):
        return {}
    try:
        with open(MANUAL_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def merge_manual(data):

    manual = load_manual()

    for k, v in manual.items():
        v["priority"] = 999  # 🔥 her zaman kazanır
        data[k] = v

    return data

# ======================================================
# MANUAL OVERRIDE
# ======================================================

def load_manual():
    if not os.path.exists(MANUAL_FILE):
        return {}
    try:
        with open(MANUAL_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def merge_manual(data):
    manual = load_manual()
    data.update(manual)
    return data


# 👇 BURAYA EKLE
# ======================================================
# MANUAL MERGE + CLEAN
# ======================================================

def load_manual_brut():
    try:
        with open("data/manual_brut.json","r") as f:
            return json.load(f)
    except:
        return {}


def clean_expired(data):

    today = datetime.now().date()
    cleaned = {}

    for sym,d in data.items():

        end = d.get("end_date")

        if not end or end == "-":
            cleaned[sym] = d
            continue

        try:
            end_dt = datetime.strptime(end,"%d.%m.%Y").date()

            if end_dt >= today:
                cleaned[sym] = d

        except:
            cleaned[sym] = d

    return cleaned
# ======================================================
# 🔥 1. KAP API
# ======================================================

def fetch_vbts():

    urls = [
        "https://www.kap.org.tr/tr/api/vbts",
        "https://www.kap.org.tr/en/api/vbts"
    ]

    results = {}

    for url in urls:

        try:
            r = requests.get(url, headers=HEADERS, timeout=8)

            if r.status_code != 200:
                continue

            data = r.json()

            for item in data:

                tedbir = str(item.get("measureType", "")).upper()

                if "BRUT" not in tedbir and "BRÜT" not in tedbir:
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
                    "start_date": start_dt.strftime("%d.%m.%Y") if start_dt else "-",
                    "end_date": end_dt.strftime("%d.%m.%Y") if end_dt else "-",
                    "days_left": days_left,
                    "type": tedbir or "Brüt Takas",
                    "priority": 100
                }

            if results:
                print(f"✅ KAP API BRÜT: {len(results)}")
                return results

        except Exception as e:
            print("KAP API error:", e)
            continue

    print("⚠ KAP API FAILED")
    return {}


# ======================================================
# 🔥 2. İŞ YATIRIM
# ======================================================

def fetch_isyatirim_brut():

    url = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/VBTSList"

    results = {}

    try:
        r = requests.post(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            return results

        data = r.json().get("d", {}).get("data", [])

        for item in data:

            text = str(item).upper()

            if "BRÜT" not in text and "BRUT" not in text:
                continue

            code = item.get("Kod")
            if not code:
                continue

            symbol = normalize_symbol(code)

            start_dt = parse_date_safe(item.get("BaslangicTarihi"))
            end_dt = parse_date_safe(item.get("BitisTarihi"))

            results[symbol] = {
                "start_date": start_dt.strftime("%d.%m.%Y") if start_dt else "-",
                "end_date": end_dt.strftime("%d.%m.%Y") if end_dt else "-",
                "days_left": days_left_calc(end_dt),
                "type": "Brüt Takas (İş Yatırım)",
                "priority": 90
            }

        if results:
            print(f"🟢 ISYATIRIM BRÜT: {len(results)}")

    except Exception as e:
        print("ISYATIRIM error:", e)

    return results


# ======================================================
# 🔥 3. KAP RSS + AI
# ======================================================

def fetch_kap_news_brut():

    results = {}

    try:
        feed = feedparser.parse("https://www.kap.org.tr/tr/rss/all")

        for entry in feed.entries[:30]:

            title = entry.title.lower()

            if "brüt" not in title and "brut" not in title:
                continue

            try:
                r = requests.get(entry.link, headers=HEADERS, timeout=8)

                html = r.text

                ai_data = gemini_parse_brut(html)

                results.update(ai_data)

            except:
                continue

    except Exception as e:
        print("KAP RSS ERROR:", e)

    return results


# ======================================================
# 🔥 4. DOVIZ HABER + AI
# ======================================================

def fetch_doviz_news_brut():

    base_url = "https://m.doviz.com"
    list_url = "https://m.doviz.com/haber/borsa-haberleri/"

    results = {}

    try:
        r = requests.get(list_url, headers=HEADERS, timeout=10)

        links = re.findall(r'href="(/haber/[^"]+)"', r.text)

        for link in set(links)[:15]:

            try:
                full_url = base_url + link
                hr = requests.get(full_url, headers=HEADERS, timeout=8)

                text = hr.text

                if "brüt" not in text.lower():
                    continue

                ai_data = gemini_parse_brut(text)

                results.update(ai_data)

            except:
                continue

    except Exception as e:
        print("DOVIZ ERROR:", e)

    return results


# ======================================================
# 🔥 MERGE
# ======================================================

def merge_all(*sources):

    final = {}

    for source in sources:

        for k, v in source.items():

            if k not in final:
                final[k] = v
            else:
                if v.get("priority", 0) > final[k].get("priority", 0):
                    final[k] = v

    return final


# ======================================================
# 🔥 MAIN ENGINE
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
        return BRUT_CACHE

    kap = fetch_vbts()
    isy = fetch_isyatirim_brut()
    kap_news = fetch_kap_news_brut()
    doviz = fetch_doviz_news_brut()

    final = merge_all(kap, isy, kap_news, doviz)

    final = merge_manual(final)
    final = clean_expired(final)

    if not final:
        print("❌ BRÜT BOŞ → CACHE")
        return BRUT_CACHE

    BRUT_CACHE = final
    LAST_UPDATE = now

    print(f"🔥 FINAL BRÜT: {len(final)}")

    return final


# ======================================================
# 🔥 HALT DETECTOR
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

            if vol_ma and last["Volume"] < vol_ma * 0.05:
                return True

        return False

    except:
        return False


# ======================================================
# 🔥 HALT CACHE
# ======================================================

LAST_HALT_CACHE = set()
LAST_HALT_UPDATE = None
HALT_CACHE_TTL = 30


def get_halt_list(data=None):

    global LAST_HALT_CACHE, LAST_HALT_UPDATE

    now = datetime.now()

    if LAST_HALT_UPDATE and (now - LAST_HALT_UPDATE).seconds < HALT_CACHE_TTL:
        return LAST_HALT_CACHE

    halt_set = set()

    if not data:
        return halt_set

    try:

        for item in data:

            symbol = item.get("symbol")

            if not symbol:
                continue

            if detect_halt_from_data(item):
                halt_set.add(symbol)

    except Exception as e:
        print("HALT scan error:", e)

    LAST_HALT_CACHE = halt_set
    LAST_HALT_UPDATE = now

    print(f"⛔ HALT SAYISI: {len(halt_set)}")

    return halt_set


# ======================================================
# 🚀 MOMENTUM FAZ ANALİZİ
# ======================================================

def validate_tradeable_momentum(df, price):

    try:

        low_30 = df["Low"].rolling(30).min().iloc[-1]
        move_pct = (price - low_30) / low_30

        if move_pct > 0.05:
            return False, "GEÇ KALINMIŞ"

        last5 = df["Close"].iloc[-5:]
        move5 = (last5.iloc[-1] - last5.iloc[0]) / last5.iloc[0]

        if move5 > 0.03:
            return False, "PARABOLİK (TEHLİKELİ)"

        if move_pct < 0.02:
            return True, "ERKEN"
        elif move_pct < 0.04:
            return True, "ORTA"
        else:
            return True, "GEÇ"

    except:
        return False, None


# ======================================================
# 🚀 PULLBACK DETECTOR
# ======================================================

def detect_pullback_entry(df, price):

    try:

        if df is None or len(df) < 25:
            return False, None

        low = df["Low"].iloc[-20:-10].min()
        high = df["High"].iloc[-10:-3].max()

        move_pct = (high - low) / low

        if move_pct < 0.025:
            return False, None

        last_high = df["High"].iloc[-3]
        pullback_pct = (last_high - price) / last_high

        if pullback_pct < 0.005:
            return False, None

        if pullback_pct > 0.03:
            return False, None

        ema20 = df["Close"].ewm(span=20).mean().iloc[-1]

        if price < ema20:
            return False, None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        if not (last["Close"] > last["Open"] and last["Close"] > prev["Close"]):
            return False, None

        vol_ma = df["Volume"].rolling(20).mean().iloc[-1]

        if last["Volume"] < vol_ma:
            return False, None

        return True, round(pullback_pct * 100, 2)

    except:
        return False, None
