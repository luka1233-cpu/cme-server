"""
macro_engine.py — V1

Arhitektura je dizajnirana za proširivost:
- Signal funkcije vracaju float (-1.0 do +1.0)
- V1: samo -1.0, 0.0, +1.0
- V2+: granularniji score (npr. +0.3, +0.7) bez promene engine-a
- Tezine su po kategorijama, ne po indikatorima
- Nedostajuci indikatori se proporcijalno preraspodeljuju
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from .signal_functions import get_signal, get_signal_value

# Uvozi NEUTRAL_WEIGHT_FACTOR iz centralne konfiguracije
sys.path.insert(0, str(Path(__file__).parent.parent / "collectors"))
from indicator_config import NEUTRAL_WEIGHT_FACTOR

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# ── Model V1 — kategorije sa tezinama ─────────────────────
# Svaka kategorija moze imati vise indikatora.
# Ako kategorija ima vise indikatora, uzima se prosek signala.
# Ako kategorija nema podataka, njena tezina se preraspodeljuje.
#
# PROSIRIVANJE: samo dodaj novi indicator_type u listu indikatora
# kategorije — engine automatski uzima prosek.
MODEL = [
    {
        "category":   "GDP",
        "weight":     0.20,
        "indicators": ["GDP"],
        "ind_weights": {"GDP": 1.0},
        "label":      "GDP Growth",
    },
    {
        "category":   "CPI",
        "weight":     0.15,
        "indicators": ["CPI", "CORE_CPI", "HICP", "PCE"],
        "ind_weights": {"CPI": 1.0, "CORE_CPI": 0.8, "HICP": 1.0, "PCE": 0.7},
        "label":      "Inflation",
    },
    {
        "category":   "EMPLOYMENT",
        "weight":     0.15,
        "indicators": ["NFP", "EMPLOYMENT", "ADP", "UNEMPLOYMENT", "JOBLESS_CLAIMS", "JOLTS"],
        "ind_weights": {"NFP": 1.0, "EMPLOYMENT": 0.9, "ADP": 0.3,
                        "UNEMPLOYMENT": 0.6, "JOBLESS_CLAIMS": 0.3, "JOLTS": 0.3},
        "label":      "Employment",
    },
    {
        "category":   "PMI_MFG",
        "weight":     0.10,
        "indicators": ["PMI_MFG"],
        "ind_weights": {"PMI_MFG": 1.0},
        "label":      "PMI Manufacturing",
    },
    {
        "category":   "PMI_SVC",
        "weight":     0.10,
        "indicators": ["PMI_SVC", "PMI_COMP"],
        "ind_weights": {"PMI_SVC": 1.0, "PMI_COMP": 0.6},
        "label":      "PMI Services",
    },
    {
        "category":   "RETAIL",
        "weight":     0.10,
        "indicators": ["RETAIL_SALES"],
        "ind_weights": {"RETAIL_SALES": 1.0},
        "label":      "Retail Sales",
    },
    {
        "category":   "RATES",
        "weight":     0.10,
        "indicators": ["INTEREST_RATE", "WAGES"],
        "ind_weights": {"INTEREST_RATE": 1.0, "WAGES": 0.6},
        "label":      "Interest Rate / Wages",
    },
    {
        "category":   "PPI",
        "weight":     0.05,
        "indicators": ["PPI"],
        "ind_weights": {"PPI": 1.0},
        "label":      "PPI",
    },
    {
        "category":   "CONFIDENCE",
        "weight":     0.05,
        "indicators": ["CONFIDENCE", "INDUSTRIAL_PROD", "TRADE_BALANCE", "CURRENT_ACCOUNT"],
        "ind_weights": {"CONFIDENCE": 1.0, "INDUSTRIAL_PROD": 0.6,
                        "TRADE_BALANCE": 0.05, "CURRENT_ACCOUNT": 0.05},
        "label":      "Confidence / Other",
    },
]

# Validacija: tezine moraju biti 1.0
assert abs(sum(c["weight"] for c in MODEL) - 1.0) < 0.001, "Weights must sum to 1.0"


def _category_signal(category: dict, indicators: dict) -> tuple[float | None, list[dict]]:
    """
    Racuna weighted signal za jednu kategoriju.
    Koristi ind_weights za relativnu vaznost unutar kategorije.
    """
    weighted_sum  = 0.0
    total_weight  = 0.0
    factors = []
    ind_weights = category.get("ind_weights", {})

    for itype in category["indicators"]:
        if itype not in indicators:
            continue
        data = indicators[itype]
        # Smer (string) za prikaz; numericka vrednost (V1 ±1 ili V2 float) za agregaciju
        signal_str = get_signal(
            itype,
            data.get("actual"),
            data.get("forecast"),
            data.get("previous"),
        )
        signal_val = get_signal_value(
            itype,
            data.get("actual"),
            data.get("forecast"),
            data.get("previous"),
        )
        ind_w = ind_weights.get(itype, 1.0)

        weighted_sum += signal_val * ind_w
        total_weight += ind_w

        factors.append({
            "indicator":    itype,
            "signal":       signal_str,
            "signal_value": round(signal_val, 3),
            "ind_weight":   ind_w,
            "actual":       data.get("actual"),
            "forecast":     data.get("forecast"),
            "previous":     data.get("previous"),
            "surprise_diff": data.get("surprise_diff"),
            "event_name":   data.get("event_name", ""),
            "release_date": data.get("release_date", ""),
            "impact":       data.get("impact", "medium"),
        })

    if total_weight == 0:
        return None, []

    avg = weighted_sum / total_weight
    return avg, factors


def compute_currency(ccy: str, indicators: dict) -> dict:
    """
    Za jednu valutu racuna Macro Score i Heatmap %.

    Algoritam (hibridni pristup, jul 2026):
    1. Za svaku kategoriju racunaj avg signal
    2. Kategorije bez podataka se preskacaju
    3. NEUTRALNE kategorije ulaze sa smanjenom tezinom (NEUTRAL_WEIGHT_FACTOR)
       - ne ignorisu se potpuno (nose informaciju)
       - ali ne razblazuju jasne bullish/bearish signale punom tezinom
    4. Tezine se normalizuju na osnovu efektivnih tezina
    5. Weighted sum -> normalizacija na 0-100%
    """
    available_categories = []

    for cat in MODEL:
        signal, factors = _category_signal(cat, indicators)
        if signal is not None:
            available_categories.append({
                "category": cat["category"],
                "label":    cat["label"],
                "weight":   cat["weight"],
                "signal":   signal,
                "factors":  factors,
            })

    if not available_categories:
        return _empty_result(ccy)

    # Hibridni pristup: neutralne kategorije dobijaju smanjenu efektivnu tezinu
    weighted_sum = 0.0
    total_effective_weight = 0.0
    categories_out = []

    for cat in available_categories:
        # Signal string za prikaz i za odredjivanje efektivne tezine
        if cat["signal"] > 0.15:
            sig_str = "bullish"
        elif cat["signal"] < -0.15:
            sig_str = "bearish"
        else:
            sig_str = "neutral"

        # Neutralna kategorija -> smanjena tezina
        effective_weight = cat["weight"] * (NEUTRAL_WEIGHT_FACTOR if sig_str == "neutral" else 1.0)

        weighted_sum += cat["signal"] * effective_weight
        total_effective_weight += effective_weight

        categories_out.append({
            "category":      cat["category"],
            "label":         cat["label"],
            "weight_orig":   round(cat["weight"], 3),
            "weight_eff":    round(effective_weight, 3),
            "signal":        sig_str,
            "signal_value":  round(cat["signal"], 3),
            "factors":       cat["factors"],
        })

    if total_effective_weight == 0:
        return _empty_result(ccy)

    normalized = weighted_sum / total_effective_weight

    # Heatmap %: 0-100, 50 = neutral
    heatmap_pct = round((normalized + 1.0) / 2.0 * 100)
    heatmap_pct = max(0, min(100, heatmap_pct))

    # Macro Score: -100 do +100
    macro_score = round(normalized * 100)

    bias = _bias_from_heatmap(heatmap_pct)

    bull = sum(1 for c in categories_out if c["signal"] == "bullish")
    bear = sum(1 for c in categories_out if c["signal"] == "bearish")
    neut = sum(1 for c in categories_out if c["signal"] == "neutral")

    total_orig_weight = sum(c["weight"] for c in available_categories)

    print(f"  {ccy}: heatmap={heatmap_pct}%, score={macro_score:+d}, bias={bias} "
          f"(bull={bull} bear={bear} neut={neut}, "
          f"coverage={round(total_orig_weight*100)}%)")

    return {
        "ccy":              ccy,
        "heatmap":          heatmap_pct,
        "macro_score":      macro_score,
        "bias":             bias,
        "bull_count":       bull,
        "bear_count":       bear,
        "neutral_count":    neut,
        "model_coverage":   round(total_orig_weight, 3),
        "categories":       categories_out,
        # Backward compat — flatten factors za HTML prikaz
        "factors":          {f["indicator"]: f
                             for cat in categories_out
                             for f in cat["factors"]},
    }


def _bias_from_heatmap(pct: int) -> str:
    if pct >= 80: return "sbull"
    if pct >= 65: return "bull"
    if pct >= 55: return "wbull"
    if pct >= 45: return "neut"
    if pct >= 35: return "wbear"
    if pct >= 20: return "bear"
    return "sbear"


def _empty_result(ccy: str) -> dict:
    return {
        "ccy": ccy, "heatmap": 50, "macro_score": 0, "bias": "neut",
        "bull_count": 0, "bear_count": 0, "neutral_count": 0,
        "model_coverage": 0.0, "categories": [], "factors": {},
    }


def run(collected_data: dict) -> dict:
    print("[macro_engine] Computing Macro Scores (category model)...")
    results = {}
    for ccy, indicators in collected_data.items():
        if not indicators:
            print(f"  {ccy}: no data")
            results[ccy] = _empty_result(ccy)
            continue
        results[ccy] = compute_currency(ccy, indicators)

    _save_heatmap(results)
    return results


def _save_heatmap(results: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source":      "FMP Economic Calendar (auto)",
        "model":       "V1 — category weighted, signal: -1/0/+1",
        "currencies":  results,
    }
    out = OUTPUT_DIR / "heatmap.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[macro_engine] Saved → {out}")
