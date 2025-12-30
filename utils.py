# utils.py
import math
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

# =====================================================
# FALLBACK SYMBOL LIST (EKSİKSİZ – SENİN LİSTEN)
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
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Istanbul"))

# =====================================================
# RSI & EMA
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

def moving_averages(df, windows=[20, 50, 100, 200]):
    result = {}
    for w in windows:
        result[w] = df["Close"].rolling(w, min_periods=1).mean().iloc[-1] if "Close" in df else None
    return result

# =====================================================
# DESTEK / DİRENÇ
# =====================================================
def detect_support_resistance_break(df, lookback=20):
    if df is None or df.empty:
        return False, False
    if not {"High", "Low", "Close"}.issubset(df.columns):
        return False, False
    if len(df) < lookback + 1:
        return False, False

    history = df.iloc[:-1].tail(lookback)
    support = history["Low"].min()
    resistance = history["High"].max()
    close = df["Close"].iloc[-1]

    return close < support, close > resistance

def nearest_support_resistance_from_history(df, lookback=100):
    if df is None or df.empty:
        return None, None
    highs = df["High"].rolling(3, center=True).max()
    lows = df["Low"].rolling(3, center=True).min()
    ph = df["High"][df["High"] == highs].dropna()
    pl = df["Low"][df["Low"] == lows].dropna()
    current = df["Close"].iloc[-1]

    resistance = min([v for v in ph if v > current], default=None)
    support = max([v for v in pl if v < current], default=None)
    return support, resistance

# =====================================================
# FORMASYONLAR
# =====================================================
def detect_three_peaks(close_series):
    if close_series is None or len(close_series) < 5:
        return False
    peaks = (close_series > close_series.shift(1)) & (close_series > close_series.shift(-1))
    idx = close_series[peaks].index
    if len(idx) < 3:
        return False
    last_three = close_series.loc[idx[-3:]]
    return close_series.iloc[-1] > last_three.max()

def detect_order_block(df, lookback=20):
    if df is None or len(df) < lookback:
        return False
    body = abs(df["Close"] - df["Open"])
    avg_body = body.rolling(lookback).mean()
    return body.iloc[-1] > avg_body.iloc[-1] * 2
