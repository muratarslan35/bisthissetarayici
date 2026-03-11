from datetime import datetime

WATCHLIST = {}
WATCH_DURATION = 10  # dakika


def add_to_watchlist(symbol):

    WATCHLIST[symbol] = datetime.now()


def in_watchlist(symbol):

    if symbol not in WATCHLIST:
        return False

    start = WATCHLIST[symbol]

    diff = (datetime.now() - start).total_seconds() / 60

    if diff > WATCH_DURATION:
        WATCHLIST.pop(symbol)
        return False

    return True


def get_watchlist():

    now = datetime.now()
    active = []

    for sym, t in list(WATCHLIST.items()):

        diff = (now - t).total_seconds() / 60

        if diff <= WATCH_DURATION:
            active.append(sym)
        else:
            WATCHLIST.pop(sym)

    return active
