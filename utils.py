import math
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np


# =====================================================
# FALLBACK SYMBOLS (SENİN LİSTEN – EKSİKSİZ)
# =====================================================
FALLBACK_SYMBOLS = [
"ADESE.IS","ADEL.IS","AEFES.IS","AGHOL.IS","AGLYO.IS","AHGAZ.IS","AHSKY.IS","AKBNK.IS","AKENR.IS",
"AKGRT.IS","AKSA.IS","AKSEN.IS","ALARK.IS","ALCTL.IS","ALFAS.IS","ALGN.IS","ALKIM.IS","ALMAD.IS",
"ANELE.IS","ARDYZ.IS","ARMDA.IS","ARTI.IS","ASELS.IS","ASUZU.IS","ATEKS.IS","ATPET.IS",
"ATLAS.IS","ATSYH.IS","ATTP.IS","AVGYO.IS","AVHOL.IS","AVOD.IS","AYCES.IS","AYDEM.IS","AYEN.IS",
"BALSU.IS","BERA.IS","BIMAS.IS","BLCYT.IS","BOBET.IS","BRKSN.IS","BRYAT.IS","BSRN.IS","BTCIM.IS","BURCE.IS",
"CANTE.IS","CCOLA.IS","CEMAS.IS","CEMTS.IS","CGLYO.IS","CMENT.IS","CIMSA.IS","CLEBI.IS","COMDO.IS",
"CUSAN.IS","DAGHL.IS","DENGE.IS","DERIM.IS","DESA.IS","DEVA.IS","DGNMO.IS","DIRIT.IS","DITAS.IS",
"DZGYO.IS","EGEEN.IS","EGGUB.IS","EGPRO.IS","EKGYO.IS","EMKEL.IS","ENKAI.IS","ENJSA.IS","ERCB.IS",
"EREGL.IS","ERSU.IS","EUREN.IS","FROTO.IS","FFKRL.IS","FMIZP.IS","FONET.IS","GARAN.IS","GEDZA.IS",
"GENIL.IS","GEREL.IS","GLBMD.IS","GLRYH.IS","GOZDE.IS","GRSAN.IS","GUBRF.IS","GZNMI.IS","HALKB.IS",
"HEKTS.IS","HRKLB.IS","IHLGM.IS","IHGZT.IS","INDES.IS","INVEO.IS","ISATR.IS","ISBTR.IS","ISCTR.IS",
"ISFIN.IS","ISGYO.IS","ISKPL.IS","ISMEN.IS","ITTFH.IS","IZMDC.IS","JANTS.IS","KAPLM.IS","KARMA.IS",
"KARSN.IS","KATMR.IS","KENT.IS","KERVT.IS","KIMMR.IS","KLGYO.IS","KLMSN.IS","KNFRT.IS","KONTR.IS",
"KONYA.IS","KORDS.IS","KOTON.IS","KOZAA.IS","KOZAL.IS","KRDMA.IS","KRDMB.IS","KRDMD.IS","KRGYO.IS",
"KRONT.IS","LIDER.IS","LINK.IS","LOGO.IS","LPCIP.IS","LUKSK.IS","MAGEN.IS","MAKIM.IS","MAVI.IS",
"MAALT.IS","MARTI.IS","MEPET.IS","MGROS.IS","MIATK.IS","MPARK.IS","MTRKS.IS","NETAS.IS","NIBAS.IS",
"ODAS.IS","OYAYO.IS","OTKAR.IS","OYLUM.IS","OZBAL.IS","PAMEL.IS","PANEL.IS","PARSN.IS","PEGAS.IS",
"PEKGY.IS","PETKM.IS","PETUN.IS","PGSUS.IS","PKART.IS","PKENT.IS","POLTK.IS","PRKAB.IS","PRZMA.IS",
"PSDTC.IS","QNBFL.IS","QUAGR.IS","RAYSG.IS","RODRG.IS","RTALB.IS","RYGYO.IS","SAFKR.IS","SANEL.IS",
"SASA.IS","SARKY.IS","SAHOL.IS","SDTTR.IS","SEKUR.IS","SELVA.IS","SEGYO.IS","SELEC.IS","SISE.IS",
"SILVR.IS","SKBNK.IS","SMART.IS","SMBYO.IS","SNICA.IS","SOKE.IS","SOKM.IS","SOMA.IS","SUNTK.IS",
"SUWEN.IS","SYHGYO.IS","TATGD.IS","TAVHL.IS","TCELL.IS","TDGYO.IS","TEHOL.IS","TEPLO.IS","THYAO.IS",
"TKFEN.IS","TKNSA.IS","TLMAN.IS","TMSN.IS","TMTAS.IS","TOASO.IS","TRCAS.IS","TRGYO.IS","TRILC.IS",
"TSGBD.IS","TSGYO.IS","TSKB.IS","TSPOR.IS","TTRAK.IS","TUKAS.IS","TUPRS.IS","TUREX.IS","ULAS.IS",
"ULKER.IS","UNLU.IS","USAK.IS","UZERB.IS","VAKBN.IS","VBTYZ.IS","VERUS.IS","VKING.IS","VESBE.IS",
"VESPA.IS","VESTL.IS","YEOTK.IS","YGGYO.IS","YKBNK.IS","YONGA.IS","YUNSA.IS","YYAPI.IS","ZEDUR.IS","ZOREN.IS"
]


# =====================================================
# TIMEZONE
# =====================================================
def to_tr_timezone(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Istanbul"))


# =====================================================
# INDICATORS
# =====================================================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


# =====================================================
# TRADINGVIEW LIVE PRICE
# =====================================================
def fetch_tradingview_price(symbol):
    try:
        url = "https://scanner.tradingview.com/turkey/scan"
        payload = {
            "symbols": {"tickers": [f"BIST:{symbol.replace('.IS','')}"], "query": {"types": []}},
            "columns": ["close"]
        }
        r = requests.post(url, json=payload, timeout=5)
        data = r.json()
        return float(data["data"][0]["d"][0])
    except Exception:
        return None


# =====================================================
# HAYALİ MUM (LIVE CLOSE ENTEGRASYONU)
# =====================================================
def apply_virtual_candle(df, live_price):
    if df.empty:
        return df

    df = df.copy()
    last_idx = df.index[-1]

    df.loc[last_idx, "Close"] = live_price
    df.loc[last_idx, "High"] = max(df.loc[last_idx, "High"], live_price)
    df.loc[last_idx, "Low"] = min(df.loc[last_idx, "Low"], live_price)

    return df


# =====================================================
# TIMEFRAME BUILDER
# =====================================================
def enrich_df(df, live_price):
    df = apply_virtual_candle(df, live_price)

    df["RSI"] = calculate_rsi(df["Close"])
    df["EMA20"] = calculate_ema(df["Close"], 20)
    df["EMA50"] = calculate_ema(df["Close"], 50)
    df["EMA100"] = calculate_ema(df["Close"], 100)
    df["EMA200"] = calculate_ema(df["Close"], 200)

    return df


def build_timeframes(df_5m, df_15m, df_1h, df_4h):
    """
    signal_engine için tek merkezli veri
    """
    return {
        "5m": df_5m,
        "15m": df_15m,
        "1h": df_1h,
        "4h": df_4h
}
