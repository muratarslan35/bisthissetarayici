import requests
from bs4 import BeautifulSoup
from datetime import datetime


BRUT_CACHE = {}
LAST_UPDATE = None


def get_brut_list():

    global BRUT_CACHE, LAST_UPDATE

    now = datetime.now()

    # günde 1 kez çek
    if LAST_UPDATE and (now - LAST_UPDATE).days == 0:
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

    except:
        pass

    BRUT_CACHE = brut_map
    LAST_UPDATE = now

    return brut_map
