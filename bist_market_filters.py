import requests
import re
from datetime import datetime
from dateutil import parser
import feedparser
import json
import os

# ======================================================
# 🔥 GEMINI AI (NEW SDK + SAFE JSON)
# ======================================================

from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = None

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Gemini aktif")
    except Exception as e:
        print("❌ Gemini init error:", e)


def extract_json_safe(text):
    try:
        if not text:
            return []

        text = text.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\[.*\]", text, re.DOTALL)

        if match:
            return json.loads(match.group(0))

        return []

    except Exception as e:
        print("JSON PARSE ERROR:", e)
        return []


def gemini_parse_brut(text):

    try:

        if not client:
            return {}

        text = text[:15000]

        prompt = f"""
Aşağıdaki metinden SADECE brüt takas hisselerini çıkar.

Kurallar:
- Sadece hisse kodu (örn: ASELS)
- Tahmin yapma
- Emin değilsen ekleme
- JSON dışında hiçbir şey yazma
- Boşsa [] dön

Format:
[
  {{"symbol": "XXX"}}
]

Metin:
{text}
"""

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        data = extract_json_safe(response.text)

        results = {}

        for item in data:
            sym = item.get("symbol")

            if not sym:
                continue

            sym = sym.upper().replace(".IS", "") + ".IS"

            if len(sym) > 8:
                continue

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
# 🔥 HTML SOURCE (BAN SAFE)
# ======================================================

def fetch_brut_html_sources():

    urls = [
        "https://www.kap.org.tr/tr/rss/all",
        "https://m.doviz.com/haber/borsa-haberleri/"
    ]

    pages = []

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)

            if r.status_code != 200:
                continue

            text = r.text.lower()

            if any(x in text for x in ["brüt", "brut", "vbts"]):
                pages.append(r.text[:15000])

        except Exception as e:
            print("HTML FETCH ERROR:", e)

    return pages


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
        v["priority"] = 999
        data[k] = v

    return data


# ======================================================
# MANUAL CLEAN
# ======================================================

def clean_expired(data):

    today = datetime.now().date()
    cleaned = {}

    for sym, d in data.items():

        end = d.get("end_date")

        if not end or end == "-":
            cleaned[sym] = d
            continue

        try:
            end_dt = datetime.strptime(end, "%d.%m.%Y").date()

            if end_dt >= today:
                d["days_left"] = (end_dt - today).days
                cleaned[sym] = d

        except:
            cleaned[sym] = d

    return cleaned


# ======================================================
# 🔥 MAIN ENGINE (FIXED)
# ======================================================

def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    if LAST_UPDATE and (now - LAST_UPDATE).seconds < CACHE_TTL:
        return BRUT_CACHE

    results = {}

    # 🔥 HTML + AI
    pages = fetch_brut_html_sources()

    for page in pages:
        try:
            ai_data = gemini_parse_brut(page)
            results.update(ai_data)
        except Exception as e:
            print("AI PARSE ERROR:", e)

    # 🔥 MANUAL HER ZAMAN
    results = merge_manual(results)
    results = clean_expired(results)

    if not results:
        print("❌ BRÜT YOK → MANUAL")
        return merge_manual({})

    BRUT_CACHE = results
    LAST_UPDATE = now

    print(f"🔥 BRÜT TOPLAM: {len(results)}")

    return results


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
