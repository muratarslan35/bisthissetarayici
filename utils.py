import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

# ==================================================
# FALLBACK SYMBOLS  (❗ AYNEN KORUNDU – EKSİK YOK)
# ==================================================
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

# ==================================================
# RSI (AYNEN KORUNDU)
# ==================================================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).fillna(50)

# ==================================================
# SUPPORT / RESISTANCE BREAK (AYNEN)
# ==================================================
def detect_support_resistance_break(df, lookback=20):
    prev_low = df["Low"].iloc[:-1].rolling(lookback, min_periods=1).min().iloc[-1]
    prev_high = df["High"].iloc[:-1].rolling(lookback, min_periods=1).max().iloc[-1]
    close = df["Close"].iloc[-1]
    return close < prev_low, close > prev_high

# ==================================================
# NEAREST SUPPORT / RESISTANCE (MESAJ + DASHBOARD)
# ==================================================
def nearest_support_resistance_from_history(df, lookback=100):
    highs = df["High"].rolling(3, center=True).max()
    lows = df["Low"].rolling(3, center=True).min()
    ph = df["High"][df["High"] == highs]
    pl = df["Low"][df["Low"] == lows]

    price = df["Close"].iloc[-1]

    resistances = [v for v in ph if v > price]
    supports = [v for v in pl if v < price]

    nearest_support = max(supports) if supports else None
    nearest_resistance = min(resistances) if resistances else None

    return nearest_support, nearest_resistance

# ==================================================
# RESISTANCE BREAK + DEVAM MESAJI (YENİ)
# ==================================================
def resistance_continuation(current_price, nearest_resistance, tolerance_pct=0.3):
    if not nearest_resistance:
        return False, False

    broken = current_price > nearest_resistance
    diff_pct = ((current_price - nearest_resistance) / nearest_resistance) * 100
    continuation = broken and diff_pct >= tolerance_pct

    return broken, continuation

# ==================================================
# TIMEZONE (AYNEN)
# ==================================================
def to_tr_timezone(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Europe/Istanbul"))
def detect_three_peaks(close_series):
    if close_series is None or close_series.empty or len(close_series) < 5:
        return False

    peaks = (
        (close_series.shift(1) < close_series) &
        (close_series.shift(-1) < close_series)
    )

    peak_prices = close_series[peaks]
    if len(peak_prices) < 3:
        return False

    last_three = peak_prices.iloc[-3:]
    max_peak = last_three.max()
    current_price = close_series.iloc[-1]

    return current_price > max_peak
