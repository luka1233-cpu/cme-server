"""
heatmap_audit.py
Audit alat za Heatmap V1 zakljucavanje.

Za svaku valutu poredi indikator-po-indikator:
  - nas signal (iz macro_raw.json kroz signal_functions)
  - A1 signal (rucno unet iz EdgeFinder screenshotova)

Svaka razlika se klasifikuje kao:
  BUG          - greska u nasem kodu (collector ili signal logika)
  DATA_SOURCE  - FMP i A1 koriste razlicite podatke/revizije/mesece
  METHODOLOGY  - isti podaci, razlicita filozofija praga/logike (dokumentovano)
  UNKNOWN      - jos nije objasnjeno

Kriterijum zakljucavanja V1: 0 x BUG + 0 x UNKNOWN.

Upotreba:
  1. Popuni A1_DATA dict ispod (sa screenshotova, isti dan kao macro_raw.json)
  2. python heatmap_audit.py path/do/macro_raw.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "engine"))
from engines.signal_functions import get_signal

# ══════════════════════════════════════════════════════════════════
# A1 EDGEFINDER PODACI — popuniti sa screenshotova (isti dan!)
# Format: ccy -> indicator_type -> {actual, forecast, signal}
# signal: 'bullish' | 'bearish' | 'neutral'
# Indikatori koje A1 nema — ne unositi (nece se porediti).
# ══════════════════════════════════════════════════════════════════
# Snimljeno: 3. jul 2026 (US heatmap timestamp 22:05)
A1_DATA = {
    "USD": {  # A1 Impact: 70%
        "GDP":            {"actual": 2.1,  "forecast": 1.6,  "signal": "bullish"},
        "PMI_MFG":        {"actual": 53.3, "forecast": 53.8, "signal": "bearish"},
        "PMI_SVC":        {"actual": 54.5, "forecast": 53.7, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": 0.9,  "forecast": 0.5,  "signal": "bullish"},
        "CPI":            {"actual": 4.2,  "forecast": 4.2,  "signal": "neutral"},
        "PPI":            {"actual": 6.5,  "forecast": 6.4,  "signal": "bullish"},
        "PCE":            {"actual": 3.4,  "forecast": 3.4,  "signal": "neutral"},
        "WAGES":          {"actual": 3.5,  "forecast": 3.5,  "signal": "neutral"},
        "UNEMPLOYMENT":   {"actual": 4.2,  "forecast": 4.3,  "signal": "bullish"},
        "JOBLESS_CLAIMS": {"actual": 215,  "forecast": 220,  "signal": "bullish"},
        "JOLTS":          {"actual": 7.59, "forecast": 7.28, "signal": "bullish"},
        "ADP":            {"actual": 98,   "forecast": 118,  "signal": "bearish"},
        "NFP":            {"actual": 57,   "forecast": 114,  "signal": "bearish"},
    },
    "EUR": {  # A1 Impact: 57.14%
        "GDP":            {"actual": -0.2, "forecast": 0.1,  "signal": "bearish"},
        "PMI_MFG":        {"actual": 51.4, "forecast": 51.3, "signal": "bullish"},
        "PMI_SVC":        {"actual": 49.4, "forecast": 48.9, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": -0.4, "forecast": -0.3, "signal": "bearish"},
        "CPI":            {"actual": 2.8,  "forecast": 3.0,  "signal": "bearish"},
        "PPI":            {"actual": 4.9,  "forecast": 4.8,  "signal": "bullish"},
        "UNEMPLOYMENT":   {"actual": 6.2,  "forecast": 6.3,  "signal": "bullish"},
    },
    "GBP": {  # A1 Impact: 60%
        "GDP":            {"actual": 0.6,  "forecast": 0.6,  "signal": "neutral"},
        "PMI_MFG":        {"actual": 52.5, "forecast": 53.1, "signal": "bearish"},
        "PMI_SVC":        {"actual": 48.8, "forecast": 48.7, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": 1.2,  "forecast": 0.5,  "signal": "bullish"},
        "CPI":            {"actual": 2.8,  "forecast": 3.0,  "signal": "bearish"},
        "PPI":            {"actual": 4.0,  "forecast": 4.0,  "signal": "neutral"},
        "UNEMPLOYMENT":   {"actual": 4.9,  "forecast": 5.0,  "signal": "bullish"},
    },
    "JPY": {  # A1 Impact: 83.33%
        "GDP":            {"actual": 0.5,  "forecast": 0.5,  "signal": "neutral"},
        "PMI_MFG":        {"actual": 54.8, "forecast": 54.9, "signal": "bearish"},
        "PMI_SVC":        {"actual": 52.2, "forecast": 51.8, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": 5.3,  "forecast": 3.1,  "signal": "bullish"},
        "CPI":            {"actual": 1.5,  "forecast": None, "signal": "bullish"},
        "PPI":            {"actual": 6.3,  "forecast": 5.6,  "signal": "bullish"},
        "UNEMPLOYMENT":   {"actual": 2.5,  "forecast": 2.5,  "signal": "neutral"},
    },
    "CHF": {  # A1 Impact: 66.67%
        "GDP":            {"actual": 0.7,  "forecast": 0.5,  "signal": "bullish"},
        "PMI_MFG":        {"actual": 54.3, "forecast": 56.4, "signal": "bearish"},
        "PMI_SVC":        {"actual": 49.4, "forecast": 48.9, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": 3.5,  "forecast": 1.8,  "signal": "bullish"},
        "CPI":            {"actual": 0.5,  "forecast": 0.5,  "signal": "neutral"},
        "PPI":            {"actual": -1.8, "forecast": None, "signal": "bullish"},
        "UNEMPLOYMENT":   {"actual": 3.0,  "forecast": 2.9,  "signal": "bearish"},
    },
    "CAD": {  # A1 Impact: 85.71%
        "GDP":            {"actual": 0.0,  "forecast": None, "signal": "bullish"},
        "PMI_MFG":        {"actual": 53.0, "forecast": None, "signal": "bullish"},
        "PMI_SVC":        {"actual": 50.6, "forecast": None, "signal": "bullish"},
        "RETAIL_SALES":   {"actual": 1.0,  "forecast": None, "signal": "bullish"},
        "CPI":            {"actual": 3.2,  "forecast": 3.0,  "signal": "bullish"},
        "PPI":            {"actual": 13.6, "forecast": 14.0, "signal": "bearish"},
        "UNEMPLOYMENT":   {"actual": 6.6,  "forecast": 6.9,  "signal": "bullish"},
    },
    "AUD": {  # A1 Impact: 40%
        "GDP":            {"actual": 0.3,  "forecast": 0.5,  "signal": "bearish"},
        "PMI_MFG":        {"actual": 51.5, "forecast": 51.2, "signal": "bullish"},
        "PMI_SVC":        {"actual": 50.5, "forecast": 49.9, "signal": "bullish"},
        "CPI":            {"actual": 4.0,  "forecast": 4.4,  "signal": "bearish"},
        "PPI":            {"actual": 3.0,  "forecast": None, "signal": "bearish"},
        "UNEMPLOYMENT":   {"actual": 4.4,  "forecast": 4.4,  "signal": "neutral"},
    },
    "NZD": {  # A1 Impact: 57.14%
        "GDP":            {"actual": 0.8,  "forecast": 0.9,  "signal": "bearish"},
        "PMI_MFG":        {"actual": 49.9, "forecast": None, "signal": "bearish"},
        "PMI_SVC":        {"actual": 47.5, "forecast": None, "signal": "bearish"},
        "RETAIL_SALES":   {"actual": 0.9,  "forecast": 0.5,  "signal": "bullish"},
        "CPI":            {"actual": 3.1,  "forecast": 2.9,  "signal": "bullish"},
        "PPI":            {"actual": 0.8,  "forecast": 0.5,  "signal": "bullish"},
        "UNEMPLOYMENT":   {"actual": 5.3,  "forecast": 5.4,  "signal": "bullish"},
    },
}

# ══════════════════════════════════════════════════════════════════
# KLASIFIKACIJE — popunjavati tokom audita.
# Format: (ccy, indicator_type) -> ("KATEGORIJA", "objasnjenje")
# Sve neklasifikovane razlike se prikazuju kao UNKNOWN.
# ══════════════════════════════════════════════════════════════════
CLASSIFICATIONS = {
    # === DATA_SOURCE — FMP i A1 koriste razlicite podatke/serije/mesece ===
    ("EUR", "GDP"):          ("DATA_SOURCE", "FMP final revision (0.6) vs A1 preliminary (-0.2)"),
    ("EUR", "RETAIL_SALES"): ("DATA_SOURCE", "FMP drugaciji mesec/serija vs A1 april (-0.4)"),
    ("EUR", "PPI"):          ("DATA_SOURCE", "Razlicite PPI serije (FMP MoM vs A1 YoY)"),
    ("USD", "WAGES"):        ("DATA_SOURCE", "Razlicite serije: FMP 1.2 vs 0.4, A1 Wage Growth YoY 3.5"),
    ("USD", "PCE"):          ("DATA_SOURCE", "FMP PCE MoM (0.4 vs 0.5) vs A1 PCE YoY (3.4 vs 3.4)"),
    ("JPY", "CPI"):          ("DATA_SOURCE", "FMP CPI serija (1.9) vs A1 National CPI (1.5)"),
    ("CHF", "GDP"):          ("DATA_SOURCE", "FMP 0.4 vs A1 0.7 — razlicita revizija/serija"),
    ("AUD", "CPI"):          ("DATA_SOURCE", "FMP mesecni indikator (3.6) vs A1 kvartalni CPI YoY (4.0)"),
    ("CAD", "RETAIL_SALES"): ("DATA_SOURCE", "FMP 0.5 vs A1 1.0 — razlicit mesec"),
    ("NZD", "RETAIL_SALES"): ("DATA_SOURCE", "FMP serija 1.0 vs 0.8, A1 QoQ 0.9 vs 0.5"),
    ("NZD", "CPI"):          ("DATA_SOURCE", "FMP QoQ (0.9) vs A1 YoY (3.1)"),
    ("CAD", "PMI_MFG"):      ("DATA_SOURCE", "FMP ima forecast 53.4 (miss); A1 bez forecasta, poredi vs prev 52.9 (beat)"),

    # === METHODOLOGY — isti podaci, dokumentovana razlika u filozofiji ===
    ("USD", "JOBLESS_CLAIMS"): ("METHODOLOGY", "Nas prag 3% (istorijski kalibrisan); -2.3% ispod praga. A1 flaguje svaki beat"),
    ("NZD", "GDP"):            ("METHODOLOGY", "-0.1pp ispod naseg GDP praga 0.2; A1 flaguje svaki surprise"),
    ("GBP", "PMI_SVC"):        ("METHODOLOGY", "Beat +0.1 < prag 0.3 -> apsolutni nivo 48.8<49 = bearish (kontrakcija). A1 cist surprise"),
    ("JPY", "PMI_MFG"):        ("METHODOLOGY", "Miss -0.1 < prag 0.3 -> apsolutni nivo 54.8>51 = bullish (ekspanzija). A1 cist surprise"),
}


def audit(macro_raw_path: str):
    with open(macro_raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    total_diff = 0
    counts = {"BUG": 0, "DATA_SOURCE": 0, "METHODOLOGY": 0, "UNKNOWN": 0, "MATCH": 0}
    unknowns = []

    for ccy, a1_indicators in A1_DATA.items():
        if not a1_indicators:
            continue
        our = raw["data"].get(ccy, {})
        print(f"\n{'=' * 78}")
        print(f"{ccy}")
        print(f"{'=' * 78}")
        print(f"  {'Indicator':<16} {'Our data':>16} {'A1 data':>16} {'Our':>8} {'A1':>8}  Status")
        print(f"  {'-' * 74}")

        for itype, a1 in a1_indicators.items():
            fmp = our.get(itype)
            if fmp is None:
                counts["DATA_SOURCE"] += 1
                total_diff += 1
                print(f"  {itype:<16} {'MISSING':>16} "
                      f"{str(a1['actual']) + ' vs ' + str(a1.get('forecast')):>16} "
                      f"{'—':>8} {a1['signal']:>8}  [DATA_SOURCE] FMP nema ovu seriju")
                continue

            our_sig = get_signal(itype, fmp.get("actual"),
                                 fmp.get("forecast"), fmp.get("previous"))
            our_data = f"{fmp.get('actual')} vs {fmp.get('forecast')}"
            a1_data = f"{a1['actual']} vs {a1.get('forecast')}"

            same_data = (fmp.get("actual") is not None and
                         abs(fmp["actual"] - a1["actual"]) < 0.05)
            same_sig = our_sig == a1["signal"]

            if same_sig:
                counts["MATCH"] += 1
                status = "✅ MATCH"
            else:
                total_diff += 1
                key = (ccy, itype)
                if key in CLASSIFICATIONS:
                    cat, note = CLASSIFICATIONS[key]
                    counts[cat] += 1
                    status = f"[{cat}] {note}"
                elif not same_data:
                    # Automatska sugestija: razliciti podaci -> verovatno DATA_SOURCE
                    counts["UNKNOWN"] += 1
                    unknowns.append((ccy, itype, "podaci se razlikuju — proveriti da li je DATA_SOURCE"))
                    status = "❓ UNKNOWN (razliciti podaci?)"
                else:
                    # Isti podaci, razlicit signal -> METHODOLOGY ili BUG
                    counts["UNKNOWN"] += 1
                    unknowns.append((ccy, itype, "isti podaci, razlicit signal — METHODOLOGY ili BUG"))
                    status = "❓ UNKNOWN (isti podaci!)"

            print(f"  {itype:<16} {our_data:>16} {a1_data:>16} "
                  f"{our_sig:>8} {a1['signal']:>8}  {status}")

    print(f"\n{'=' * 78}")
    print(f"REZIME")
    print(f"{'=' * 78}")
    for cat, n in counts.items():
        print(f"  {cat:<14} {n}")
    print()
    if counts["BUG"] == 0 and counts["UNKNOWN"] == 0:
        print("  ✅ KRITERIJUM ISPUNJEN: 0 BUG + 0 UNKNOWN — V1 moze da se zakljuca.")
    else:
        print(f"  ❌ Jos {counts['BUG']} BUG + {counts['UNKNOWN']} UNKNOWN — nije spremno za zakljucavanje.")
        if unknowns:
            print("\n  Za istragu:")
            for ccy, itype, hint in unknowns:
                print(f"    - {ccy} {itype}: {hint}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Upotreba: python heatmap_audit.py path/do/macro_raw.json")
        sys.exit(1)
    audit(sys.argv[1])
