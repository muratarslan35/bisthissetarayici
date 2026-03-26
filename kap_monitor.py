import requests
import json
import os
import time
import feedparser
from datetime import datetime
from kap_watchlist_engine import add_to_watchlist

STATE_FILE = "data/kap_state.json"

IMPORTANT_KEYWORDS = [
"bedelsiz","bedelli","temettü","geri alım","geri alim",
"yeni iş","yeni is","ihale","teşvik","tesvik","yatırım","yatirim"
]

TWITTER_FEEDS = [
"https://nitter.net/kapbildirim/rss",
"https://nitter.net/kapbildirimler/rss"
]

KAP_RSS = "https://www.kap.org.tr/tr/rss/all"

# 🚀 YENİ: SYMBOL COOLDOWN
SYMBOL_COOLDOWN = {}

# ---------------------------------------------------
# STATE
# ---------------------------------------------------

def load_state():

    if not os.path.exists(STATE_FILE):
        return set()

    try:
        with open(STATE_FILE,"r") as f:
            return set(json.load(f))
    except:
        return set()


def save_state(data):

    os.makedirs("data",exist_ok=True)

    with open(STATE_FILE,"w") as f:
        json.dump(list(data),f)


# ---------------------------------------------------
# 🚀 YENİ: KAP SKOR
# ---------------------------------------------------

def kap_score(title):

    t = title.lower()

    score = 0

    if "bedelsiz" in t:
        score += 30
    if "geri alım" in t or "geri alim" in t:
        score += 25
    if "ihale" in t:
        score += 20
    if "yatırım" in t or "yatirim" in t:
        score += 20
    if "temettü" in t:
        score += 15
    if "bedelli" in t:
        score -= 10

    return score


# ---------------------------------------------------
# FILTER
# ---------------------------------------------------

def is_important(text):

    text=text.lower()

    for k in IMPORTANT_KEYWORDS:
        if k in text:
            return True

    return False


# ---------------------------------------------------
# TWITTER RSS
# ---------------------------------------------------

def fetch_twitter_kap():

    results={}

    for url in TWITTER_FEEDS:

        try:

            feed=feedparser.parse(url)

            for entry in feed.entries[:20]:

                title=entry.title

                if "(" not in title:
                    continue

                symbol=title.split("(")[1].split(")")[0]
                symbol=symbol.split(",")[0]+".IS"

                results[symbol]={
                    "title":title,
                    "link":entry.link,
                    "time":datetime.now(),
                    "score": kap_score(title),  # ✅
                    "alert_sent":False
                }

        except:
            continue

    return results


# ---------------------------------------------------
# KAP RSS
# ---------------------------------------------------

def fetch_kap_rss():

    results={}

    try:

        feed=feedparser.parse(KAP_RSS)

        for entry in feed.entries[:30]:

            title=entry.title

            if not is_important(title):
                continue

            if "(" not in title:
                continue

            symbol=title.split("(")[1].split(")")[0]
            symbol=symbol.split(",")[0]+".IS"

            results[symbol]={
                "title":title,
                "link":entry.link,
                "time":datetime.now(),
                "score": kap_score(title),  # ✅
                "alert_sent":False
            }

    except:
        pass

    return results


# ---------------------------------------------------
# KAP API
# ---------------------------------------------------

def fetch_kap_api():

    url="https://www.kap.org.tr/tr/api/disclosures"

    for _ in range(3):

        try:

            r=requests.get(url,timeout=6)

            if r.status_code==200:
                return r.json()

        except:
            pass

        time.sleep(2)

    return []


# ---------------------------------------------------
# MAIN
# ---------------------------------------------------

def check_kap(fallback_symbols):

    sent=load_state()
    results={}

    now = datetime.now()

    # ---- Twitter ----

    twitter=fetch_twitter_kap()

    for sym,data in twitter.items():

        if sym not in fallback_symbols:
            continue

        # 🚀 COOLDOWN
        if sym in SYMBOL_COOLDOWN:
            if (now - SYMBOL_COOLDOWN[sym]).seconds < 600:
                continue

        key=data["link"]

        if key in sent:
            continue

        results[sym]=data
        add_to_watchlist(sym)
        sent.add(key)

        SYMBOL_COOLDOWN[sym] = now  # ✅

    # ---- RSS ----

    rss=fetch_kap_rss()

    for sym,data in rss.items():

        if sym not in fallback_symbols:
            continue

        if sym in SYMBOL_COOLDOWN:
            if (now - SYMBOL_COOLDOWN[sym]).seconds < 600:
                continue

        key=data["link"]

        if key in sent:
            continue

        results[sym]=data
        add_to_watchlist(sym)
        sent.add(key)

        SYMBOL_COOLDOWN[sym] = now

    # ---- API ----

    api=fetch_kap_api()

    for item in api[:80]:

        kap_id=str(item.get("disclosureIndex"))

        if kap_id in sent:
            continue

        title=item.get("title","")

        if not is_important(title):
            continue

        company=item.get("stockCodes","")

        if not company:
            continue

        symbol=company.split(",")[0]+".IS"

        if symbol not in fallback_symbols:
            continue

        if symbol in SYMBOL_COOLDOWN:
            if (now - SYMBOL_COOLDOWN[symbol]).seconds < 600:
                continue

        link=f"https://www.kap.org.tr/tr/Bildirim/{kap_id}"

        results[symbol]={
            "title":title,
            "link":link,
            "time":datetime.now(),
            "score": kap_score(title),  # ✅
            "alert_sent":False
        }

        add_to_watchlist(symbol)
        sent.add(kap_id)

        SYMBOL_COOLDOWN[symbol] = now

    save_state(sent)

    return results
