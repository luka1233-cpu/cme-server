"""
cot_collector.py — V2 (jul 2026)

Povlaci COT sa CFTC Socrata API-ja i racuna CME polja za TRI MODELA:

  legacy    — Non-Commercial iz Legacy Futures Only   (ono sto CME sada koristi)
  levFunds  — Leveraged Funds iz TFF Futures Only      (hedge fondovi, brzi novac)
  assetMgr  — Asset Managers iz TFF Futures Only       (institucionalni, spori novac)

Plus HISTORIJSKI PERCENTIL (3 godine) neto pozicije za svaki model.

VAZNO — score i dalje koristi model iz konfiguracije (`COT_MODEL` u
indicator_config.py, default "legacy"). Sva tri se POVLACE i PISU u cot.json,
ali se ponasanje engine-a NE menja dok cot_model_test.py ne pokaze koji je
bolji. Isti obrazac kao USE_FLOAT_SCORE: podatak prvo, odluka posle.

DATASETS (verifikovano na zivom API-ju 12 jul 2026):
  Legacy Futures Only  = 6dca-aqww   (ima sve: valute + zlato)
  TFF Futures Only     = gpe5-46if   (SAMO finansijski futures — valute; NEMA zlato)

Zlato (XAU 088691) NIJE u TFF-u. Za njega bi trebao Disaggregated izvestaj
(ekvivalent spekulanta je "Managed Money"), cija Futures-Only dataset verzija
jos nije verifikovana — zato XAU za sada ostaje samo na Legacy modelu.

Bez API kljuca — CFTC Socrata je javan.
"""

import json
import urllib.request
import urllib.parse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from indicator_config import COT_MODEL
except ImportError:
    COT_MODEL = "legacy"

OUTPUT_DIR = Path(__file__).parent.parent / "output"

SOCRATA = "https://publicreporting.cftc.gov/resource"
LEGACY_DS = "6dca-aqww"   # Legacy Futures Only
TFF_DS    = "gpe5-46if"   # TFF Futures Only

HISTORY_WEEKS    = 160  # ~3 godine — za percentil
PERCENTILE_WEEKS = 156  # tacno 3 godine

MARKETS = {
    "USD": {"code": "098662", "name": "USD INDEX",         "tff": True},
    "EUR": {"code": "099741", "name": "EURO FX",           "tff": True},
    "GBP": {"code": "096742", "name": "BRITISH POUND",     "tff": True},
    "JPY": {"code": "097741", "name": "JAPANESE YEN",      "tff": True},
    "CHF": {"code": "092741", "name": "SWISS FRANC",       "tff": True},
    "CAD": {"code": "090741", "name": "CANADIAN DOLLAR",   "tff": True},
    "AUD": {"code": "232741", "name": "AUSTRALIAN DOLLAR", "tff": True},
    "NZD": {"code": "112741", "name": "NZ DOLLAR",         "tff": True},
    # Zlato nije u TFF-u — samo Legacy dok se Disaggregated ne verifikuje
    "XAU": {"code": "088691", "name": "GOLD",              "tff": False},
}

# model -> (dataset, long polje, short polje)
MODELS = {
    "legacy":   (LEGACY_DS, "noncomm_positions_long_all", "noncomm_positions_short_all"),
    "levFunds": (TFF_DS,    "lev_money_positions_long",   "lev_money_positions_short"),
    "assetMgr": (TFF_DS,    "asset_mgr_positions_long",   "asset_mgr_positions_short"),
}


def fetch_market(dataset: str, code: str, fields: list[str],
                 limit: int = HISTORY_WEEKS) -> list[dict]:
    """Povlaci poslednjih N nedeljnih izvestaja za dati contract code."""
    params = {
        "cftc_contract_market_code": code,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(limit),
        "$select": "report_date_as_yyyy_mm_dd," + ",".join(fields),
    }
    url = f"{SOCRATA}/{dataset}.json?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[cot]   fetch greska ({dataset}): {e}")
        return []


def parse_weeks(reports: list[dict], long_f: str, short_f: str) -> list[dict]:
    """Pretvara sirove izvestaje u [{date, long, short, net, longPct}] DESC."""
    weeks = []
    for r in reports:
        try:
            l = int(float(r[long_f]))
            s = int(float(r[short_f]))
        except (KeyError, ValueError, TypeError):
            continue
        total = l + s
        if total == 0:
            continue
        weeks.append({
            "date":    (r.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "long":    l,
            "short":   s,
            "net":     l - s,
            "longPct": l / total * 100.0,
        })
    return weeks


def percentile_rank(series: list[float], value: float) -> int | None:
    """
    Percentil trenutne vrednosti u istorijskoj seriji (0-100).
    76 = trenutna neto pozicija je visa nego 76% poslednje 3 godine.
    Vraca None ako nema dovoljno istorije za smislen percentil.
    """
    vals = [v for v in series if v is not None]
    if len(vals) < 30:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return round((below + equal / 2) / len(vals) * 100)


def compute_fields(weeks: list[dict]) -> dict | None:
    """
    Racuna CME polja iz parsiranih nedelja (DESC).
    Generican — radi za bilo koji model jer prima vec parsirane long/short.
    """
    if len(weeks) < 7:
        return None

    cur, prev, w6 = weeks[0], weeks[1], weeks[6]

    # Trend Quality: koliko od 6 nedeljnih koraka ide u smeru ukupnog trenda
    overall_dir = 1 if (cur["longPct"] - w6["longPct"]) >= 0 else -1
    consistent = 0
    for i in range(6):
        step = weeks[i]["longPct"] - weeks[i + 1]["longPct"]
        step_dir = 1 if step >= 0 else -1
        if step_dir == overall_dir:
            consistent += 1

    hist = [w["net"] for w in weeks[:PERCENTILE_WEEKS]]
    pct_rank = percentile_rank(hist, cur["net"])

    return {
        "longPct":      round(cur["longPct"], 1),
        "longPct6wAgo": round(w6["longPct"], 1),
        "deltaPct6w":   round(cur["longPct"] - w6["longPct"]),
        "dLong":        cur["long"] - prev["long"],
        "dShort":       cur["short"] - prev["short"],
        "tqConsistent": consistent,
        "netPosition":  cur["net"],
        "percentile3y": pct_rank,
        "historyWeeks": len(weeks),
        "reportDate":   cur["date"],
    }


def collect() -> dict:
    """
    Vraca {ccy: fields} i pise cot.json.
    Povlaci sva tri modela; aktivni (COT_MODEL) ide na vrh radi kompatibilnosti
    sa cme.html, ostali u `models` bloku.
    """
    active = COT_MODEL if COT_MODEL in MODELS else "legacy"
    print(f"[cot] Aktivan model za score: {active}")

    results = {}
    report_date = None

    for ccy, mk in MARKETS.items():
        code = mk["code"]
        per_model = {}

        # Legacy — uvek
        ds, lf_, sf_ = MODELS["legacy"]
        raw = fetch_market(ds, code, [lf_, sf_])
        f = compute_fields(parse_weeks(raw, lf_, sf_))
        if f:
            per_model["legacy"] = f

        # TFF — samo tamo gde postoji (nema zlata)
        if mk["tff"]:
            _, lf_l, lf_s = MODELS["levFunds"]
            _, am_l, am_s = MODELS["assetMgr"]
            raw_t = fetch_market(TFF_DS, code, [lf_l, lf_s, am_l, am_s])
            for model, (lname, sname) in (("levFunds", (lf_l, lf_s)),
                                          ("assetMgr", (am_l, am_s))):
                ft = compute_fields(parse_weeks(raw_t, lname, sname))
                if ft:
                    per_model[model] = ft

        if not per_model:
            print(f"[cot] {ccy}: nema podataka ({mk['name']})")
            continue

        # Aktivni model ide na vrh (cme.html cita ta polja kao i do sad)
        base = per_model.get(active) or per_model.get("legacy")
        if not base:
            print(f"[cot] {ccy}: model '{active}' nedostupan, preskacem")
            continue

        entry = dict(base)
        entry["model"] = active if active in per_model else "legacy"
        entry["models"] = per_model

        # Divergencija LF vs AM — spori i brzi novac se ne slazu
        lf, am = per_model.get("levFunds"), per_model.get("assetMgr")
        if lf and am:
            entry["lfAmDivergence"] = {
                "lfDelta": lf["deltaPct6w"],
                "amDelta": am["deltaPct6w"],
                "opposed": (lf["deltaPct6w"] > 0) != (am["deltaPct6w"] > 0),
                "gap":     round(abs(lf["deltaPct6w"] - am["deltaPct6w"])),
            }

        results[ccy] = entry
        report_date = report_date or entry["reportDate"]

        pc = f"p{entry['percentile3y']}" if entry.get("percentile3y") is not None else "p—"
        extra = ""
        if lf and am:
            mark = " ⚠razilaze" if entry["lfAmDivergence"]["opposed"] else ""
            extra = (f" | LF {lf['longPct']}%({lf['deltaPct6w']:+d}) "
                     f"AM {am['longPct']}%({am['deltaPct6w']:+d}){mark}")
        print(f"[cot] {ccy}: Long% {entry['longPct']} "
              f"(6w ago {entry['longPct6wAgo']}, delta {entry['deltaPct6w']:+d}pp) "
              f"net {entry['netPosition']:+d} {pc} "
              f"TQ={entry['tqConsistent']}/6 [{entry['reportDate']}]{extra}")

    _save(results, report_date, active)
    _freshness(report_date)
    return results


def _save(results: dict, report_date: str | None, active: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "reportDate":  report_date,
        "scoreModel":  active,
        "modelsAvailable": list(MODELS),
        "note": "Sva tri modela se povlace; score koristi scoreModel "
                "(COT_MODEL u indicator_config.py). XAU ima samo legacy — "
                "zlato nije u TFF izvestaju.",
        "currencies":  results,
    }
    p = OUTPUT_DIR / "cot.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[cot] Saved -> {p}")


def _freshness(report_date: str | None):
    if not report_date:
        return
    try:
        d = datetime.strptime(report_date, "%Y-%m-%d").date()
    except ValueError:
        return
    age = (datetime.now(timezone.utc).date() - d).days
    print(f"[cot] Najnoviji izvestaj: {report_date} (star {age} dana)")
    if age > 10:
        print("[cot] NAPOMENA: izvestaj stariji od 10 dana — CFTC Socrata baza "
              "verovatno jos nije unela najnoviji petkov izvestaj. "
              "Pokreni ponovo za nekoliko sati / sutra.")


if __name__ == "__main__":
    collect()
