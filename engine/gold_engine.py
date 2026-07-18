"""
gold_engine.py — Gold Macro Score V1

Dva motora:
  Engine 1 — Gold Macro:  USD Growth + USD Inflation + USD Labor + 2Y Yield
                          (svi USD signali INVERTOVANI: jak USD = bearish gold)
  Engine 2 — Gold COT:    Net Positioning + Latest Buys/Sells + Extremes

Izlaz: gold.json — dva skora, ukupni bias, i AI narativ koji objasnjava
slaganje/konflikt izmedju Macro i COT.

KLJUCNA INVERZIJA: za zlato je logika obrnuta od valute.
  USD bullish  -> Gold BEARISH
  Yield rising -> Gold BEARISH (hawkish)
  COT long     -> Gold BULLISH (institucije kupuju zlato)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# ── Tezine unutar Gold Macro motora ────────────────────────
# USD makro kategorije + yield. Suma = 1.0.
GOLD_MACRO_WEIGHTS = {
    "USD_GROWTH":    0.25,   # GDP
    "USD_INFLATION": 0.25,   # CPI/PCE
    "USD_LABOR":     0.30,   # NFP/Unemployment/Claims (najjaci gold driver)
    "YIELD_2Y":      0.20,   # 2Y Treasury trend
}
assert abs(sum(GOLD_MACRO_WEIGHTS.values()) - 1.0) < 0.001

# ── Gold COT ekstrem pragovi ───────────────────────────────
COT_EXTREME_HIGH = 85.0   # Long% iznad = prenatrpano long (kontra oprez)
COT_EXTREME_LOW  = 20.0   # Long% ispod = prenatrpano short

SIG_VAL = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def _invert(signal: str) -> str:
    """Invertuje USD signal za zlato."""
    if signal == "bullish":
        return "bearish"
    if signal == "bearish":
        return "bullish"
    return "neutral"


def _category_from_macro(macro_result: dict, category: str) -> str:
    """
    Cita signal kategorije iz heatmap.json USD rezultata.
    category: 'USD_GROWTH' | 'USD_INFLATION' | 'USD_LABOR'
    Vraca USD signal (jos NIJE invertovan).
    """
    cat_map = {
        "USD_GROWTH":    ["GDP"],
        "USD_INFLATION": ["CPI"],
        "USD_LABOR":     ["EMPLOYMENT"],
    }
    wanted = cat_map.get(category, [])
    cats = macro_result.get("categories", [])
    for c in cats:
        if c.get("category") in wanted:
            return c.get("signal", "neutral")
    return "neutral"


def compute_gold_macro(usd_macro: dict, yield_trend: dict | None) -> dict:
    """
    Engine 1 — Gold Macro.
    usd_macro: USD rezultat iz heatmap.json (currencies.USD)
    yield_trend: rezultat yield_collector.collect() ili None
    """
    factors = []
    weighted_sum = 0.0
    total_weight = 0.0

    # USD makro kategorije (invertovane za zlato)
    for cat_key, weight in GOLD_MACRO_WEIGHTS.items():
        if cat_key == "YIELD_2Y":
            continue
        usd_sig = _category_from_macro(usd_macro, cat_key)
        gold_sig = _invert(usd_sig)
        val = SIG_VAL[gold_sig]
        weighted_sum += val * weight
        total_weight += weight
        factors.append({
            "factor":     cat_key,
            "usd_signal": usd_sig,
            "gold_signal": gold_sig,
            "weight":     weight,
        })

    # 2Y Yield (vec je u gold-orijentaciji: rising->bearish)
    if yield_trend is not None:
        gold_sig = yield_trend["goldSignal"]
        val = SIG_VAL[gold_sig]
        w = GOLD_MACRO_WEIGHTS["YIELD_2Y"]
        weighted_sum += val * w
        total_weight += w
        factors.append({
            "factor":      "YIELD_2Y",
            "detail":      f"2Y {yield_trend['past']}->{yield_trend['current']} "
                           f"({yield_trend['change']:+.2f}pp, {yield_trend['yieldSignal']})",
            "gold_signal": gold_sig,
            "weight":      w,
        })

    if total_weight == 0:
        return {"score": 0, "signal": "neutral", "factors": []}

    normalized = weighted_sum / total_weight
    score = round(normalized * 100)
    signal = "bullish" if normalized > 0.15 else "bearish" if normalized < -0.15 else "neutral"

    return {"score": score, "signal": signal, "factors": factors}


def compute_gold_cot(cot_xau: dict | None) -> dict:
    """
    Engine 2 — Gold COT.
    cot_xau: XAU zapis iz cot.json (currencies.XAU) ili None.
    """
    if not cot_xau:
        return {"score": 0, "signal": "neutral", "factors": [], "available": False}

    long_pct = cot_xau.get("longPct", 50)
    d_long = cot_xau.get("dLong", 0)
    d_short = cot_xau.get("dShort", 0)
    delta_6w = cot_xau.get("deltaPct6w", 0)

    factors = []

    # 1. Net Positioning — Long% (bullish za zlato ako institucije long)
    if long_pct >= 55:
        net_sig = "bullish"
    elif long_pct <= 45:
        net_sig = "bearish"
    else:
        net_sig = "neutral"
    factors.append({"factor": "NET_POSITIONING",
                    "detail": f"Long {long_pct}%",
                    "gold_signal": net_sig})

    # 2. Latest Buys/Sells — nedeljna promena (dLong - dShort)
    net_flow = d_long - d_short
    if net_flow > 2000:
        flow_sig = "bullish"
    elif net_flow < -2000:
        flow_sig = "bearish"
    else:
        flow_sig = "neutral"
    factors.append({"factor": "LATEST_FLOW",
                    "detail": f"dLong {d_long:+d}, dShort {d_short:+d}",
                    "gold_signal": flow_sig})

    # 3. Extremes — Long% na ekstremu = kontra oprez (ne menja smer, samo flag)
    extreme = None
    if long_pct >= COT_EXTREME_HIGH:
        extreme = "crowded_long"
    elif long_pct <= COT_EXTREME_LOW:
        extreme = "crowded_short"
    if extreme:
        factors.append({"factor": "EXTREME",
                        "detail": f"Long {long_pct}% = {extreme}",
                        "gold_signal": "caution"})

    # Skor: net positioning dominira, flow modifikuje
    vals = [SIG_VAL[net_sig], SIG_VAL[flow_sig] * 0.5]
    normalized = sum(vals) / 1.5
    score = round(max(-1, min(1, normalized)) * 100)
    signal = "bullish" if normalized > 0.15 else "bearish" if normalized < -0.15 else "neutral"

    return {"score": score, "signal": signal, "factors": factors,
            "available": True, "extreme": extreme}


def build_narrative(macro: dict, cot: dict) -> dict:
    """AI-style narativ koji objasnjava slaganje/konflikt Macro vs COT."""
    m_sig = macro["signal"]
    c_sig = cot["signal"]

    def phrase_sr(sig):
        return {"bullish": "bullish", "bearish": "bearish", "neutral": "neutralan"}[sig]

    def phrase_en(sig):
        return {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral"}[sig]

    sr_parts = []
    en_parts = []

    # Macro deo
    yield_factor = next((f for f in macro["factors"] if f["factor"] == "YIELD_2Y"), None)
    yield_note_sr = ""
    yield_note_en = ""
    if yield_factor and yield_factor["gold_signal"] != "neutral":
        rising = yield_factor["gold_signal"] == "bearish"
        yield_note_sr = f", 2Y prinos {'raste (dodatni bearish pritisak)' if rising else 'pada (bullish podrska)'}"
        yield_note_en = f", 2Y yield {'rising (added bearish pressure)' if rising else 'falling (bullish support)'}"

    sr_parts.append(f"USD makro je {phrase_sr(m_sig)} za zlato{yield_note_sr}.")
    en_parts.append(f"USD macro is {phrase_en(m_sig)} for gold{yield_note_en}.")

    # COT deo + konflikt
    if cot["available"]:
        if m_sig != "neutral" and c_sig != "neutral" and m_sig != c_sig:
            # Konflikt
            sr_parts.append(
                f"Ali institucionalni COT ostaje {phrase_sr(c_sig)}. "
                f"Dugorocno pozicioniranje u konfliktu sa makro slikom.")
            en_parts.append(
                f"However institutional COT remains {phrase_en(c_sig)}. "
                f"Long-term positioning conflicts with the macro picture.")
        elif m_sig == c_sig and m_sig != "neutral":
            # Slaganje
            sr_parts.append(
                f"COT to potvrdjuje ({phrase_sr(c_sig)}) — makro i institucije poravnati.")
            en_parts.append(
                f"COT confirms this ({phrase_en(c_sig)}) — macro and institutions aligned.")
        else:
            sr_parts.append(f"COT je {phrase_sr(c_sig)}.")
            en_parts.append(f"COT is {phrase_en(c_sig)}.")

        # Ekstrem upozorenje
        if cot.get("extreme") == "crowded_long":
            sr_parts.append("Napomena: Long% na ekstremu — oprez od preokreta.")
            en_parts.append("Note: Long% at extreme — caution on reversal.")
        elif cot.get("extreme") == "crowded_short":
            sr_parts.append("Napomena: Short% na ekstremu — oprez od squeeze-a.")
            en_parts.append("Note: Short% at extreme — caution on squeeze.")

    return {"sr": " ".join(sr_parts), "en": " ".join(en_parts)}


def run(usd_macro: dict, cot_xau: dict | None, yield_trend: dict | None) -> dict:
    """Glavni entry point. Pravi gold.json."""
    print("[gold] Computing Gold Macro Score V1...")

    macro = compute_gold_macro(usd_macro, yield_trend)
    cot = compute_gold_cot(cot_xau)
    narrative = build_narrative(macro, cot)

    # Ukupni bias: Macro i COT ravnopravno (50/50) osim ako COT nedostaje
    if cot["available"]:
        combined = (macro["score"] + cot["score"]) / 2
    else:
        combined = macro["score"]
    combined = round(combined)
    heatmap_pct = round((combined / 100 + 1) / 2 * 100)
    heatmap_pct = max(0, min(100, heatmap_pct))

    bias = _bias(heatmap_pct)

    print(f"[gold] Macro: {macro['signal']} ({macro['score']:+d}), "
          f"COT: {cot['signal']} ({cot['score']:+d}) => "
          f"Gold {bias} ({heatmap_pct}%)")
    print(f"[gold] {narrative['sr']}")

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "heatmap":     heatmap_pct,
        "score":       combined,
        "bias":        bias,
        "engines": {
            "macro": macro,
            "cot":   cot,
        },
        "narrative": narrative,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / "gold.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[gold] Saved -> {OUTPUT_DIR / 'gold.json'}")
    return result


def _bias(pct: int) -> str:
    if pct >= 80: return "sbull"
    if pct >= 65: return "bull"
    if pct >= 55: return "wbull"
    if pct >= 45: return "neut"
    if pct >= 35: return "wbear"
    if pct >= 20: return "bear"
    return "sbear"
