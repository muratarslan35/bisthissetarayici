import requests
import numpy as np
import pandas as pd

# ======================================================
# FALLBACK SYMBOLS
# ======================================================

FALLBACK_SYMBOLS = [
    "ADESE.IS","ADEL.IS","AEFES.IS","AGHOL.IS","AGLYO.IS","AHGAZ.IS","AHSKY.IS","AKBNK.IS","AKENR.IS",
    "AKGRT.IS","AKSA.IS","AKSEN.IS","ALARK.IS","ALCTL.IS","ALFAS.IS","ALGN.IS","ALKIM.IS","ALMAD.IS",
    "ANELE.IS","ARDYZ.IS","ARMDA.IS","ARTI.IS","ASELS.IS","ASUZU.IS","ATEKS.IS","ATPET.IS",
    "ATLAS.IS","ATSYH.IS","ATTP.IS","AVGYO.IS","AVHOL.IS","AVOD.IS","AYCES.IS","AYDEM.IS","AYEN.IS",
    "BALSU.IS","BERA.IS","BIMAS.IS","BLCYT.IS","BOBET.IS","BRKSN.IS","BRYAT.IS","BSRN.IS","BTCIM.IS","BURCE.IS",
    "CANTE.IS","CCOLA.IS","CEMAS.IS","CEMTS.IS","CGLYO.IS","CGCAM.IS","CMENT.IS","CIMSA.IS","CLEBI.IS","COMDO.IS",
    "CUSAN.IS","DAGHL.IS","DENGE.IS","DERIM.IS","DESA.IS","DEVA.IS","DGNMO.IS","DIRIT.IS","DITAS.IS",
    "DZGYO.IS","EDIP.IS","EGEEN.IS","EGGUB.IS","EGPRO.IS","EKGYO.IS","EMKEL.IS","ENKAI.IS","ENJSA.IS","ERCB.IS",
    "EREGL.IS","ERSU.IS","EUREN.IS","FROTO.IS","FMIZP.IS","FONET.IS","GARAN.IS","GEDZA.IS",
    "GENIL.IS","GEREL.IS","GLBMD.IS","GLRYH.IS","GOZDE.IS","GRSAN.IS","GUBRF.IS","GZNMI.IS","HALKB.IS",
    "HEKTS.IS","HRKLB.IS","IHLGM.IS","IHGZT.IS","INDES.IS","INVEO.IS","ISBTR.IS","ISCTR.IS",
    "ISFIN.IS","ISGYO.IS","ISKPL.IS","ISMEN.IS","ITTFH.IS","IZMDC.IS","JANTS.IS","KAPLM.IS","KARMA.IS",
    "KARSN.IS","KATMR.IS","KENT.IS","KERVT.IS","KIMMR.IS","KLGYO.IS","KLMSN.IS","KNFRT.IS","KONTR.IS",
    "KONYA.IS","KORDS.IS","KOTON.IS","KOZAA.IS","KOZAL.IS","KRDMA.IS","KRDMB.IS","KRDMD.IS","KRGYO.IS",
    "KRONT.IS","LIDER.IS","LINK.IS","LOGO.IS","LPCIP.IS","LUKSK.IS","MAGEN.IS","MAKIM.IS","MAVI.IS",
    "MAALT.IS","MARTI.IS","MEPET.IS","MGROS.IS","MIATK.IS","MPARK.IS","MTRKS.IS","NETAS.IS","NIBAS.IS",
    "ODAS.IS","OYAYO.IS","OTKAR.IS","OYLUM.IS","OZBAL.IS","PAMEL.IS","PANEL.IS","PARSN.IS","PEGAS.IS",
    "PEKGY.IS","PETKM.IS","PETUN.IS","PGSUS.IS","PKART.IS","PKENT.IS","POLTK.IS","PRKAB.IS","PRZMA.IS",
    "PSDTC.IS","PSGYO.IS","QNBFL.IS","QUAGR.IS","RAYSG.IS","RODRG.IS","RTALB.IS","RYGYO.IS","SAFKR.IS","SANEL.IS",
    "SASA.IS","SARKY.IS","SAHOL.IS","SDTTR.IS","SEKUR.IS","SELVA.IS","SEGYO.IS","SELEC.IS","SISE.IS",
    "SILVR.IS","SKBNK.IS","SMART.IS","SMBYO.IS","SMRVA.IS","SNICA.IS","SOKE.IS","SOKM.IS","SOMA.IS","SUNTK.IS",
    "SUWEN.IS","SYHGYO.IS","TATGD.IS","TAVHL.IS","TCELL.IS","TDGYO.IS","TEHOL.IS","TEPLO.IS","TERA.IS","THYAO.IS",
    "TKFEN.IS","TKNSA.IS","TLMAN.IS","TMSN.IS","TMTAS.IS","TOASO.IS","TRCAS.IS","TRGYO.IS","TRILC.IS",
    "TSGBD.IS","TSGYO.IS","TSKB.IS","TSPOR.IS","TTRAK.IS","TUKAS.IS","TUPRS.IS","TUREX.IS","ULAS.IS",
    "ULKER.IS","UNLU.IS","USAK.IS","UZERB.IS","VAKBN.IS","VBTYZ.IS","VERUS.IS","VKING.IS","VESBE.IS",
    "VESPA.IS","VESTL.IS","YEOTK.IS","YGGYO.IS","YKBNK.IS","YONGA.IS","YUNSA.IS","YYAPI.IS","ZEDUR.IS","ZOREN.IS"
]

# ======================================================
# DATETIME NORMALIZER (KRİTİK FIX)
# ======================================================

def normalize_datetime(df):
    if df is None or df.empty:
        return None

    if "Datetime" not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df["Datetime"] = df.index
            df.reset_index(drop=True, inplace=True)

    return df

# ======================================================
# SYMBOL / PRICE
# ======================================================

def resolve_symbols(data):
    if not data or not isinstance(data, dict):
        return FALLBACK_SYMBOLS
    symbols = list(data.keys())
    return symbols if symbols else FALLBACK_SYMBOLS

def fetch_tradingview_price(symbol):
    try:
        url = "https://scanner.tradingview.com/turkey/scan"
        payload = {
            "symbols": {
                "tickers": [f"BIST:{symbol.replace('.IS','')}"],
                "query": {"types": []}
            },
            "columns": ["close"]
        }
        r = requests.post(url, json=payload, timeout=5)
        data = r.json()
        return float(data["data"][0]["d"][0])
    except Exception:
        return None

# ======================================================
# SUPPORT / RESISTANCE
# ======================================================

def nearest_support_resistance_from_history(df, window=50):
    df = normalize_datetime(df)

    if df is None or len(df) < window:
        return []

    closes = df["Close"].tail(window).values
    levels = []

    for i in range(2, len(closes) - 2):
        if closes[i] > closes[i-1] and closes[i] > closes[i+1]:
            levels.append({"level": closes[i], "strength": 3})
        elif closes[i] < closes[i-1] and closes[i] < closes[i+1]:
            levels.append({"level": closes[i], "strength": 3})

    return levels

def detect_support_resistance_break(df):
    df = normalize_datetime(df)

    if df is None or len(df) < 20:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-20:-1]

    if last["Close"] > prev["High"].max():
        return {"type": "RESISTANCE_BREAK"}
    if last["Close"] < prev["Low"].min():
        return {"type": "SUPPORT_BREAK"}

    return None

# ======================================================
# PATTERN
# ======================================================

def detect_three_peaks(series):
    if series is None or len(series) < 30:
        return False

    peaks = []
    values = series.values if hasattr(series, "values") else series

    for i in range(2, len(values) - 2):
        if values[i] > values[i-1] and values[i] > values[i+1]:
            peaks.append(values[i])

    return len(peaks) >= 3

# ======================================================
# LAST RESISTANCE
# ======================================================

def get_last_resistance(df, min_strength=3):
    df = normalize_datetime(df)

    if df is None or len(df) < 30:
        return None

    levels = nearest_support_resistance_from_history(df)

    strong_levels = [
        x["level"] for x in levels
        if x.get("strength", 0) >= min_strength
    ]

    if not strong_levels:
        return None

    return round(max(strong_levels), 2)
