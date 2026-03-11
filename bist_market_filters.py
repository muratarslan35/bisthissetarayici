import requests
from bs4 import BeautifulSoup


def get_brut_list():

    url = "https://www.kap.org.tr/tr/BistTedbirleri"

    brut_list = set()

    try:

        r = requests.get(url, timeout=10)

        soup = BeautifulSoup(r.text, "html.parser")

        tables = soup.find_all("table")

        for table in tables:

            rows = table.find_all("tr")

            for row in rows:

                cols = row.find_all("td")

                if len(cols) < 2:
                    continue

                text = cols[0].text.strip()

                if "." not in text:
                    continue

                symbol = text.split(".")[0] + ".IS"

                brut_list.add(symbol)

    except:
        pass

    return brut_list


def get_halt_list():

    url = "https://www.kap.org.tr/tr/devre-kesici"

    halt_list = set()

    try:

        r = requests.get(url, timeout=10)

        soup = BeautifulSoup(r.text, "html.parser")

        tables = soup.find_all("table")

        for table in tables:

            rows = table.find_all("tr")

            for row in rows:

                cols = row.find_all("td")

                if len(cols) < 2:
                    continue

                text = cols[0].text.strip()

                if "." not in text:
                    continue

                symbol = text.split(".")[0] + ".IS"

                halt_list.add(symbol)

    except:
        pass

    return halt_list
