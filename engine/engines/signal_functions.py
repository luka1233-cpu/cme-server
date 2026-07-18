"""
signal_functions.py
Per-indicator signal logika.

Svaki indikator ima svoju funkciju koja vraca:
  'bullish' | 'neutral' | 'bearish'

Filosofija:
- Gde imamo Actual, Forecast i Previous → koristimo ih (trzisna reakcija)
- Fiksne pragove (npr. PMI > 50) koristimo samo gde zaista ima smisla
- Svaka funkcija je nezavisna i lako se menja

Pragovi:
- Svi pragovi su u THRESHOLDS dict-u u indicator_config.py
- Ne menjati brojeve direktno ovde — samo u konfiguraciji
- Istorija kalibracije je dokumentovana u indicator_config.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Uvozi centralne pragove iz indicator_config
sys.path.insert(0, str(Path(__file__).parent.parent / "collectors"))
from indicator_config import (THRESHOLDS, USE_FLOAT_SCORE,
                              FLOAT_SCORE_SATURATION)

Signal = str  # 'bullish' | 'neutral' | 'bearish'


def _t(key: str) -> float:
    """Pomocna funkcija — vraca prag za dati indicator_type."""
    return THRESHOLDS.get(key, 0.10)


# ── Helper ─────────────────────────────────────────────────

def _surprise_signal(
    actual: float | None,
    forecast: float | None,
    previous: float | None,
    threshold: float = 0.0,
    inverted: bool = False,
) -> Signal:
    """
    Osnovna surprise logika:
    1. Ako imamo Forecast → Actual vs Forecast (trzisna ocekivanja)
    2. Ako nema Forecast  → Actual vs Previous (relativna promena)
    3. threshold: minimalna razlika da bi signal bio bullish/bearish
    4. inverted: za indikatore gde visi broj = losije (Unemployment, Jobless Claims)
    """
    ref = forecast if forecast is not None else previous
    if actual is None or ref is None:
        return "neutral"

    diff = round(actual - ref, 4)  # FP zaokruzivanje — granica mora biti deterministicka
    if inverted:
        diff = -diff

    # Granicna semantika: diff JEDNAK pragu = signal (ne neutral).
    # Fix za BUG otkriven u auditu jul 2026: 4.9-5.0 vs 5.3-5.4 davali
    # razlicite rezultate zbog floating point-a na tacno pragu.
    if abs(diff) < threshold:
        return "neutral"
    return "bullish" if diff > 0 else "bearish"


def _rel_signal(
    actual: float | None,
    forecast: float | None,
    previous: float | None,
    threshold: float,
    inverted: bool = False,
) -> Signal:
    """Relativni surprise (% od forecasta) — za indikatore sa velikim apsolutnim brojevima."""
    ref = forecast if forecast is not None else previous
    if actual is None or ref is None or ref == 0:
        return "neutral"
    rel = round((actual - ref) / abs(ref), 4)  # FP zaokruzivanje
    if inverted:
        rel = -rel
    # Ista granicna semantika kao _surprise_signal: rel == prag = signal
    if rel >= threshold:
        return "bullish"
    if rel <= -threshold:
        return "bearish"
    return "neutral"


# ── Per-indicator signal funkcije ──────────────────────────

def signal_gdp(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("GDP"))


def signal_cpi(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("CPI"))


def signal_core_cpi(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("CORE_CPI"))


def signal_hicp(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("HICP"))


def signal_ppi(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("PPI"))


def signal_pce(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("PCE"))


def signal_pmi_mfg(actual, forecast, previous) -> Signal:
    """
    Manufacturing PMI.
    Surprise ima prioritet nad apsolutnim nivoom kada je znacajan.
    Apsolutni nivo (>50/<50) koristi se samo kada surprise nije znacajan.
    """
    if actual is None:
        return "neutral"
    t = _t("PMI_MFG")
    ref = forecast if forecast is not None else previous
    if ref is not None:
        diff = actual - ref
        if abs(diff) >= t:
            return "bullish" if diff > 0 else "bearish"
    # Mali surprise ili nema forecasta — koristi apsolutni nivo
    if actual > 51:
        return "bullish"
    if actual < 49:
        return "bearish"
    return "neutral"


def signal_pmi_svc(actual, forecast, previous) -> Signal:
    return signal_pmi_mfg(actual, forecast, previous)


def signal_pmi_comp(actual, forecast, previous) -> Signal:
    return signal_pmi_mfg(actual, forecast, previous)


def signal_nfp(actual, forecast, previous) -> Signal:
    """Non-Farm Payrolls — relativni threshold."""
    return _rel_signal(actual, forecast, previous, threshold=_t("NFP"))


def signal_employment(actual, forecast, previous) -> Signal:
    return _rel_signal(actual, forecast, previous, threshold=_t("EMPLOYMENT"))


def signal_adp(actual, forecast, previous) -> Signal:
    return _rel_signal(actual, forecast, previous, threshold=_t("ADP"))


def signal_unemployment(actual, forecast, previous) -> Signal:
    """INVERTED: manji broj = bullish."""
    return _surprise_signal(actual, forecast, previous,
                            threshold=_t("UNEMPLOYMENT"), inverted=True)


def signal_jobless_claims(actual, forecast, previous) -> Signal:
    """
    Initial Jobless Claims — INVERTED, relativni threshold.
    Prag kalibrisan jul 2026 na 90d podataka: 5/5 ispravnih signala.
    """
    return _rel_signal(actual, forecast, previous,
                       threshold=_t("JOBLESS_CLAIMS"), inverted=True)


def signal_jolts(actual, forecast, previous) -> Signal:
    """
    JOLTS Job Openings — relativni threshold.
    Prag kalibrisan jul 2026 na 90d podataka: 1/1 ispravnih signala.
    """
    return _rel_signal(actual, forecast, previous, threshold=_t("JOLTS"))


def signal_retail_sales(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("RETAIL_SALES"))


def signal_interest_rate(actual, forecast, previous) -> Signal:
    """
    Interest Rate Decision.
    Koristimo Previous za poredenje — hike/cut/hold.
    """
    if actual is None or previous is None:
        return "neutral"
    diff = actual - previous
    t = _t("INTEREST_RATE")
    if diff > t:
        return "bullish"
    if diff < -t:
        return "bearish"
    return "neutral"


def signal_wages(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("WAGES"))


def signal_trade_balance(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("TRADE_BALANCE"))


def signal_current_account(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("CURRENT_ACCOUNT"))


def signal_industrial_prod(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("INDUSTRIAL_PROD"))


def signal_confidence(actual, forecast, previous) -> Signal:
    return _surprise_signal(actual, forecast, previous, threshold=_t("CONFIDENCE"))


# ── Dispatch tabela ────────────────────────────────────────

SIGNAL_FUNCTIONS = {
    "GDP":            signal_gdp,
    "CPI":            signal_cpi,
    "CORE_CPI":       signal_core_cpi,
    "HICP":           signal_hicp,
    "PPI":            signal_ppi,
    "PCE":            signal_pce,
    "PMI_MFG":        signal_pmi_mfg,
    "PMI_SVC":        signal_pmi_svc,
    "PMI_COMP":       signal_pmi_comp,
    "NFP":            signal_nfp,
    "EMPLOYMENT":     signal_employment,
    "ADP":            signal_adp,
    "UNEMPLOYMENT":   signal_unemployment,
    "JOBLESS_CLAIMS": signal_jobless_claims,
    "JOLTS":          signal_jolts,
    "RETAIL_SALES":   signal_retail_sales,
    "INTEREST_RATE":  signal_interest_rate,
    "WAGES":          signal_wages,
    "TRADE_BALANCE":  signal_trade_balance,
    "CURRENT_ACCOUNT":signal_current_account,
    "INDUSTRIAL_PROD":signal_industrial_prod,
    "CONFIDENCE":     signal_confidence,
}


def get_signal(itype: str, actual, forecast, previous) -> Signal:
    """Glavni entry point — poziva pravu funkciju za dati indicator_type."""
    fn = SIGNAL_FUNCTIONS.get(itype)
    if fn is None:
        return "neutral"
    return fn(actual, forecast, previous)


# ── Indikatori koji koriste RELATIVNI surprise (% od ref) ──
# Isti spisak kao _rel_signal pozivi gore. Za float magnitudu moramo
# da znamo da li je surprise apsolutni ili relativni.
_REL_INDICATORS = {"NFP", "EMPLOYMENT", "ADP", "JOBLESS_CLAIMS", "JOLTS"}
# Invertovani (visi broj = losije) — smer vec resava get_signal, ali
# magnitude racuna |diff| pa inverzija ne menja velicinu.


def _float_magnitude(itype: str, actual, forecast, previous) -> float:
    """
    Vraca magnitudu iznenadjenja u [1/SAT .. 1.0] za dati indikator.
    Koristi isti ref (forecast pa previous) i isti tip surprise-a
    (rel vs apsolutni) kao odgovarajuca signal funkcija.
    INTEREST_RATE koristi previous kao ref (kao signal_interest_rate).
    """
    threshold = _t(itype)
    if itype == "INTEREST_RATE":
        ref = previous
    else:
        ref = forecast if forecast is not None else previous
    if actual is None or ref is None:
        return 1.0  # fallback — smer postoji, daj pun

    if itype in _REL_INDICATORS and ref != 0:
        diff = (actual - ref) / abs(ref)
    else:
        diff = actual - ref

    diff = round(abs(diff), 4)
    if threshold <= 0:
        return 1.0
    mag = diff / (threshold * FLOAT_SCORE_SATURATION)
    # clamp: minimum 1/SAT (na samom pragu nije 0), maksimum 1.0
    return max(1.0 / FLOAT_SCORE_SATURATION, min(1.0, mag))


def get_signal_value(itype: str, actual, forecast, previous) -> float:
    """
    Vraca NUMERICKU vrednost signala za agregaciju u macro_engine.

    V1 (USE_FLOAT_SCORE=False): diskretno -1.0 / 0.0 / +1.0
    V2 (USE_FLOAT_SCORE=True):  float skaliran magnitudom iznenadjenja

    Smer UVEK dolazi iz get_signal() (cuva svu V1 logiku — PMI pravila,
    inverzije, INTEREST_RATE). Float samo skalira velicinu bullish/bearish
    signala; neutral je uvek 0.0.
    """
    sig = get_signal(itype, actual, forecast, previous)
    if sig == "neutral":
        return 0.0
    direction = 1.0 if sig == "bullish" else -1.0

    if not USE_FLOAT_SCORE:
        return direction  # V1 ponasanje

    magnitude = _float_magnitude(itype, actual, forecast, previous)
    return direction * magnitude
