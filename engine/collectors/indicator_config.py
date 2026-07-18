"""
indicator_config.py
Centralna konfiguracija za macro engine.

DIZAJN PRINCIPI:
- Jedan izvor podataka: FMP Economic Calendar
- Konzistentan algoritam za svih 8 valuta
- Nema per-currency hakova da bi se imitirao A1 ili drugi sistemi

POZNATE RAZLIKE U ODNOSU NA A1 EDGEFINDER:
  EUR: FMP i A1 koriste razlicite release-e i revizije za GDP, Retail,
       CPI i PPI. Ovo je posledica razlicitih izvora podataka, ne greske
       u algoritmu. Odluka (jul 2026): prihvatamo razliku, ne uvodimo
       per-currency izuzetke.

ISTORIJA KALIBRACIJE:
  JOBLESS_CLAIMS: 0.05 -> 0.03 (jul 2026, test 90d: 5/5 ispravnih signala)
  JOLTS:          0.05 -> 0.03 (jul 2026, test 90d: 1/1 ispravnih signala)
"""

# ==============================================================
# MODE - filozofija Heatmap izracuna
# ==============================================================
# "CALIBRATED"    - neutral_weight kalibrisan sweep testom vs A1
# "A1"            - neutrali ignorisani (bullish/bullish+bearish stil)
# "CONSERVATIVE"  - neutrali sa punom tezinom (razblazuju ka 50%)
#
# Jednim stringom menjas filozofiju celog engine-a.

MODE = "CALIBRATED"

_MODE_NEUTRAL_WEIGHTS = {
    "CALIBRATED":   0.3,   # sweep test jul 2026: avg greska 3.33pp
                            # (0.0 -> 6.00pp, 0.5 -> 5.33pp, 1.0 -> 8.33pp)
                            # na USD/GBP/JPY snapshot; EUR iskljucen
                            # (dokazana razlika FMP vs A1 izvora)
                            # NAPOMENA: 1 snapshot, 3 valute — za pravu
                            # validaciju treba visenedeljna A1 istorija
    "A1":           0.0,
    "CONSERVATIVE": 1.0,
}

NEUTRAL_WEIGHT_FACTOR = _MODE_NEUTRAL_WEIGHTS[MODE]

# ==============================================================
# FLOAT SCORE (Engine V2) — signal skaliran po jacini iznenadjenja
# ==============================================================
# V1: signal je diskretan -1/0/+1 (svaki surprise preko praga = pun ±1)
# V2: signal je float skaliran magnitudom iznenadjenja preko praga
#
#   ako |diff| < prag  -> 0.0 (neutral, isto kao V1)
#   inace -> sign(diff) × clamp(|diff| / (prag × SATURATION), 1/SAT .. 1.0)
#
# SATURATION = koliko puta veci od praga surprise mora biti za pun ±1.0.
# Izbor 3.0 (jul 2026): na realnim FMP podacima 3× jedini zadrzava pun
# uticaj pravih jakih iznenadjenja (RETAIL_SALES 5.3 vs 3.2, PPI 6.3 vs
# 5.5) dok tesne signale (GDP 0.5 vs 0.3, PMI jedva preko) spusta na ~1/3.
# 5×/8× su guslili i prave signale. V1 je davao JPY 90% jer je 7 tesnih
# signala tretirao kao pun +1; V2×3 to realnije prikazuje kao ~60%.
#
# KAD DODJE OUTCOME TRACKING: menjaj samo SATURATION i meri uspesnost
# (3× vs 4× vs 5× -> % tacnih signala), bez diranja engine-a.

USE_FLOAT_SCORE = True   # False = vrati se na V1 diskretni -1/0/+1
FLOAT_SCORE_SATURATION = 3.0

# ==============================================================
# COT MODEL — koja kategorija trgovaca vodi score
# ==============================================================
# CFTC daje isti market kroz vise izvestaja sa razlicitom podelom trgovaca:
#
#   "legacy"    Non-Commercial iz Legacy Futures Only (6dca-aqww)
#               = Asset Managers + Leveraged Funds + Other, SVE SABIJENO U JEDNO
#
#   "levFunds"  Leveraged Funds iz TFF Futures Only (gpe5-46if)
#               = hedge fondovi, brzi novac, reaguju prvi ali vise suma
#
#   "assetMgr"  Asset Managers iz TFF Futures Only (gpe5-46if)
#               = penzioni/institucionalni, spori novac, redje ali trajnije
#
# Zasto ovo postoji: Legacy sabija AM i LF u jedan broj iako cesto stoje na
# SUPROTNIM stranama. Realni EUR podaci: Asset Mgr +237K net LONG dok su
# Leveraged Funds -36K net SHORT. Legacy od toga pravi kasu.
#
# Collector POVLACI sva tri bez obzira na ovu postavku (svi su u cot.json pod
# `models`), ali SCORE koristi samo ovaj. Default "legacy" = nepromenjeno
# ponasanje dok cot_model_test.py ne pokaze koji je model bolji na istoriji.
#
# XAU ima samo "legacy" — zlato nije u TFF izvestaju (trebao bi Disaggregated,
# gde je ekvivalent "Managed Money"). Za XAU se automatski koristi legacy.

COT_MODEL = "legacy"   # "legacy" | "levFunds" | "assetMgr"

# ==============================================================
# THRESHOLDS - menjaj ovde, ne u signal_functions.py
# ==============================================================
THRESHOLDS = {
    # Relativni pragovi (% od forecasta)
    "NFP":            0.10,   # Non-Farm Payrolls
    "EMPLOYMENT":     0.10,   # Employment Change
    "ADP":            0.10,   # ADP Employment
    "JOBLESS_CLAIMS": 0.03,   # Kalibrisan jul 2026 (5/5 ispravnih)
    "JOLTS":          0.03,   # Kalibrisan jul 2026 (1/1 ispravnih)

    # Apsolutni pragovi (pp ili indeksni poeni)
    "GDP":            0.20,
    "CPI":            0.10,
    "CORE_CPI":       0.10,
    "HICP":           0.10,
    "PCE":            0.10,
    "PPI":            0.20,
    "PMI_MFG":        0.30,
    "PMI_SVC":        0.30,
    "PMI_COMP":       0.30,
    "RETAIL_SALES":   0.20,
    "WAGES":          0.10,
    "CONFIDENCE":     0.50,
    "TRADE_BALANCE":  0.50,
    "CURRENT_ACCOUNT":0.50,
    "INDUSTRIAL_PROD":0.20,
    "INTEREST_RATE":  0.01,   # hike/cut prag u pp
    "UNEMPLOYMENT":   0.10,
}

# ==============================================================
# Per-currency preferred event liste
# ==============================================================

GDP_PREFERRED = {
    "USD": ["gdp annualized", "gdp growth rate qoq", "gdp qoq", "gdp yoy"],
    "EUR": ["gdp growth rate qoq", "gdp qoq", "gdp growth qoq", "gdp yoy"],
    "GBP": ["gdp mom", "gdp growth mom", "gdp qoq", "gdp yoy"],
    "JPY": ["gdp growth rate qoq", "gdp qoq", "gdp yoy"],
    "CHF": ["gdp growth rate qoq", "gdp qoq", "gdp yoy"],
    "CAD": ["gdp mom", "gdp growth mom", "gdp qoq", "gdp yoy"],
    "AUD": ["gdp growth rate qoq", "gdp qoq", "gdp yoy"],
    "NZD": ["gdp growth rate qoq", "gdp qoq", "gdp yoy"],
}

CPI_PREFERRED = {
    "USD": ["cpi yoy", "cpi mom", "consumer price index yoy"],
    "EUR": ["hicp yoy", "cpi yoy", "hicp mom"],
    "GBP": ["cpi yoy", "cpi mom"],
    "JPY": ["cpi yoy", "cpi mom", "national cpi"],
    "CHF": ["cpi yoy", "cpi mom"],
    "CAD": ["cpi yoy", "cpi mom"],
    "AUD": ["cpi yoy", "cpi mom", "trimmed mean cpi"],
    "NZD": ["cpi yoy", "cpi qoq"],
}

RETAIL_PREFERRED = {
    "USD": ["retail sales mom", "retail sales"],
    "EUR": ["retail sales mom", "retail sales yoy"],
    "GBP": ["retail sales mom", "retail sales yoy"],
    "JPY": ["retail sales yoy", "retail sales mom"],
    "CHF": ["retail sales yoy", "retail sales mom"],
    "CAD": ["retail sales mom", "retail sales"],
    "AUD": ["retail sales mom", "retail sales qoq"],
    "NZD": ["retail sales qoq", "retail sales mom"],
}

PMI_MFG_PREFERRED = {
    "USD": ["ism manufacturing pmi", "manufacturing pmi", "s&p global manufacturing"],
    "EUR": ["s&p global manufacturing pmi", "manufacturing pmi", "markit manufacturing"],
    "GBP": ["s&p global manufacturing pmi", "manufacturing pmi", "markit manufacturing"],
    "JPY": ["manufacturing pmi", "s&p global manufacturing", "jibun bank manufacturing"],
    "CHF": ["manufacturing pmi", "procure.ch manufacturing"],
    "CAD": ["manufacturing pmi", "s&p global manufacturing"],
    "AUD": ["manufacturing pmi", "s&p global manufacturing", "judo bank manufacturing"],
    "NZD": ["manufacturing pmi", "bno manufacturing"],
}

PMI_SVC_PREFERRED = {
    "USD": ["ism services pmi", "ism non-manufacturing", "services pmi", "s&p global services"],
    "EUR": ["s&p global services pmi", "services pmi", "markit services"],
    "GBP": ["s&p global services pmi", "services pmi", "markit services"],
    "JPY": ["services pmi", "s&p global services", "jibun bank services"],
    "CHF": ["services pmi"],
    "CAD": ["services pmi", "s&p global services"],
    "AUD": ["services pmi", "s&p global services", "judo bank services"],
    "NZD": ["services pmi"],
}

EMPLOYMENT_PREFERRED = {
    "USD": ["nonfarm payrolls", "non farm payrolls", "non-farm payrolls"],
    "EUR": ["employment change qoq", "employment change", "payrolls"],
    "GBP": ["employment change", "claimant count change", "payrolls"],
    "JPY": ["jobs/applications ratio", "employment change", "labor force"],
    "CHF": ["employment change", "jobs"],
    "CAD": ["employment change", "net change in employment"],
    "AUD": ["employment change", "full time employment"],
    "NZD": ["employment change qoq", "employment change"],
}

INTEREST_RATE_PREFERRED = {
    "USD": ["fed interest rate decision", "federal funds rate", "interest rate decision"],
    "EUR": ["interest rate decision", "ecb interest rate", "main refinancing rate"],
    "GBP": ["interest rate decision", "bank rate", "boe interest rate"],
    "JPY": ["boj interest rate decision", "interest rate decision", "overnight rate"],
    "CHF": ["interest rate decision", "snb interest rate", "policy rate"],
    "CAD": ["boc interest rate decision", "overnight rate", "interest rate decision"],
    "AUD": ["rba interest rate decision", "cash rate", "interest rate decision"],
    "NZD": ["rbnz interest rate decision", "official cash rate", "interest rate decision"],
}

INDICATOR_PREFERRED = {
    "GDP":           GDP_PREFERRED,
    "CPI":           CPI_PREFERRED,
    "RETAIL_SALES":  RETAIL_PREFERRED,
    "PMI_MFG":       PMI_MFG_PREFERRED,
    "PMI_SVC":       PMI_SVC_PREFERRED,
    "EMPLOYMENT":    EMPLOYMENT_PREFERRED,
    "INTEREST_RATE": INTEREST_RATE_PREFERRED,
}

RETAIL_EXCLUSIONS = ["ex gas", "ex autos", "ex-gas", "ex-autos", "excluding", "control group"]


def preferred_score(event_name: str, indicator_type: str, ccy: str) -> int:
    """
    Vraca prioritet eventa (veci = bolji).
    0 = nema preferencijalnog matcha (genericki)
    1+ = pozicija u preferred listi (veci = visi prioritet)
    """
    config = INDICATOR_PREFERRED.get(indicator_type)
    if not config:
        return 0

    preferred_list = config.get(ccy, [])
    if not preferred_list:
        return 0

    name = event_name.lower()
    for i, keyword in enumerate(reversed(preferred_list)):
        kw_words = keyword.split()
        if not all(w in name for w in kw_words):
            continue
        if indicator_type == "RETAIL_SALES":
            if any(excl in name for excl in RETAIL_EXCLUSIONS):
                continue
        return i + 1

    return 0
