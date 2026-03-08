import requests
import json
import os
from datetime import datetime

STATE_FILE = "data/kap_state.json"

IMPORTANT_KEYWORDS = [
"bedelsiz",
"bedelli",
"temettü",
"geri alım",
"geri alim",
"yeni iş",
"yeni is",
"ihale",
"teşvik",
"tesvik",
"yatırım",
"yatirim"
]

def load_state():

    if not os.path.exists(STATE_FILE):
        return set()

    with open(STATE_FILE,"r") as f:
        return set(json.load(f))


def save_state(data):

    os.makedirs("data",exist_ok=True)

    with open(STATE_FILE,"w") as f:
        json.dump(list(data),f)


def fetch_kap():

    url="https://www.kap.org.tr/tr/api/disclosures"

    r=requests.get(url,timeout=10)

    if r.status_code!=200:
        return []

    return r.json()


def is_important(text):

    text=text.lower()

    for k in IMPORTANT_KEYWORDS:
        if k in text:
            return True

    return False


def check_kap(fallback_symbols):

    sent=load_state()

    data=fetch_kap()

    results={}

    for item in data[:50]:

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

        link=f"https://www.kap.org.tr/tr/Bildirim/{kap_id}"

        results[symbol]={
            "title":title,
            "link":link,
            "time":datetime.now()
        }

        sent.add(kap_id)

    save_state(sent)

    return results
