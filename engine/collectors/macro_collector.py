"""
macro_collector.py
Povlaci najnovije makro podatke sa FMP stable/economic-calendar API-ja.
Za svaku valutu vraca poslednju objavu svakog pracenog indikatora.
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .indicator_config import preferred_score

FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
OUTPUT_DIR  = Path(__file__).parent.parent / "output"
DAYS_BACK   = 90

CURRENCY_COUNTRIES = {
    "USD": ["US"],
    "EUR": ["EU", "DE", "FR", "IT", "ES"],
    "GBP": ["GB", "UK"],
    "JPY": ["JP"],
    "CHF": ["CH"],
    "CAD": ["CA"],
    "AUD": ["AU"],
    "NZD": ["NZ"],
}

# ── Precizni keyword matching ─────────────────────────────────────────────────
# Svaki entry: (required_keyword, exclude_keywords, indicator_type, impact)
# required_keyword mora biti u nazivu (case-insensitive)
# exclude_keywords su reci koje NE smeju biti u nazivu
INDICATOR_MAP = [
    # GDP — specificni nazivi imaju prioritet (redosled je vazan!)
    # Iskljuceni: Capital Expenditure, Price Index/deflator/Implicit, GDPNow, Sales,
    #             Potential, Private Consumption, External Demand (pod-komponente)
    ("gdp growth",       ["gdpnow","projection","forecast","atlanta","estimate","price","deflator","implicit","potential","per capita","sales","capital expenditure","capex","private consumption","external demand"], "GDP", "high"),
    ("real gdp",         ["gdpnow","projection","forecast","atlanta","estimate","price","deflator","implicit","capital expenditure","capex","private consumption","external demand"], "GDP", "high"),
    ("gross domestic product", ["gdpnow","projection","price","deflator","implicit","sales","capital expenditure","capex","private consumption","external demand"], "GDP", "high"),
    ("gdp",              ["gdpnow","projection","forecast","atlanta","estimate","price index","deflator","implicit","potential","per capita","sales","capital expenditure","capex","expenditure","private consumption","external demand","quits","final","advance preliminary"], "GDP", "high"),

    # PMI — Manufacturing mora biti eksplicitan, iskljuci New Orders, sub-indekse
    ("ism manufacturing",["new orders","prices","employment","backlog","inventory","deliveries"], "PMI_MFG", "high"),
    ("manufacturing pmi", ["services","composite","new orders","prices"], "PMI_MFG", "high"),
    ("manufacturing purchasing", ["services","composite"], "PMI_MFG", "high"),
    ("s&p global manufacturing", ["new orders","prices"], "PMI_MFG", "high"),

    # PMI Services
    ("ism services",     ["manufacturing"], "PMI_SVC", "high"),
    ("services pmi",     ["manufacturing","composite"], "PMI_SVC", "high"),
    ("s&p global services", [], "PMI_SVC", "high"),

    # PMI Composite
    ("composite pmi",    [], "PMI_COMP", "medium"),
    ("s&p global composite", [], "PMI_COMP", "medium"),

    # NFP — mora biti "nonfarm payrolls" bez "private" (koristimo total)
    # Ako nema total, prihvatamo private kao fallback
    ("nonfarm payroll",  ["private","adp"], "NFP", "high"),
    ("non-farm payroll", ["private","adp"], "NFP", "high"),
    ("non farm payroll", ["private","adp"], "NFP", "high"),

    # Employment — ADP i employment change
    ("adp employment",   [], "ADP", "medium"),
    ("employment change",["adp","cost","jobless"], "EMPLOYMENT", "high"),

    # Unemployment — samo U-3 (headline), ne U-6
    ("unemployment rate", ["u-6","u6","broad","long"], "UNEMPLOYMENT", "high"),

    # Inflation — redosled je vazan (specificnije prvo)
    ("core cpi",         [], "CORE_CPI", "high"),
    ("core inflation",   [], "CORE_CPI", "high"),
    ("hicp",             ["core"], "HICP", "high"),
    ("cpi",              ["core","hicp"], "CPI", "high"),
    ("consumer price",   ["core"], "CPI", "high"),

    # PPI
    ("ppi",              ["core","ex food","ex-food","trade"], "PPI", "medium"),
    ("producer price",   ["core"], "PPI", "medium"),

    # PCE — headline, ne core
    ("pce price index",  ["core"], "PCE", "high"),
    ("personal consumption expenditure", ["core"], "PCE", "high"),

    # Interest Rate — samo stvarna stopa, ne projekcije
    ("interest rate",    ["projection","forecast","expectation","year","yr","overnight rate target"], "INTEREST_RATE", "high"),
    ("bank rate",        ["projection"], "INTEREST_RATE", "high"),
    ("cash rate",        ["projection"], "INTEREST_RATE", "high"),
    ("overnight rate",   ["target","projection"], "INTEREST_RATE", "high"),
    ("fed funds",        ["projection","target range"], "INTEREST_RATE", "high"),
    ("base rate",        ["projection"], "INTEREST_RATE", "high"),

    # Wages — samo stvarni podaci, ne projekcije
    ("average earnings", ["projection"], "WAGES", "medium"),
    ("wage growth",      [], "WAGES", "medium"),
    ("employment cost",  ["index"], "WAGES", "medium"),

    # Retail Sales — headline only, ne "ex gas/autos" varijante
    ("retail sales",     ["ex gas","ex autos","ex-gas","ex-autos","excluding","control group"], "RETAIL_SALES", "high"),

    # Jobless Claims — initial only, iskljuci continuing i 4-week average
    ("initial jobless",  [], "JOBLESS_CLAIMS", "medium"),
    ("jobless claims",   ["continued","continuing","4-week","4 week","insured"], "JOBLESS_CLAIMS", "medium"),

    # JOLTS — Job Openings only, ne Quits ili Hires
    ("jolts job openings", [], "JOLTS", "medium"),
    ("job openings",     ["quits","hires","layoffs","jolts quits"], "JOLTS", "medium"),

    # Trade
    ("trade balance",    ["goods trade balance adv"], "TRADE_BALANCE", "medium"),
    ("goods trade balance", ["adv","advance"], "TRADE_BALANCE", "medium"),
    ("current account",  [], "CURRENT_ACCOUNT", "medium"),

    # Other
    ("industrial production", [], "INDUSTRIAL_PROD", "medium"),
    ("consumer confidence", [], "CONFIDENCE", "medium"),
    ("business confidence", [], "CONFIDENCE", "medium"),
    ("consumer sentiment",  [], "CONFIDENCE", "medium"),
]


def fetch_calendar(api_key: str, days_back: int) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days_back)
    params = {"from": start.isoformat(), "to": today.isoformat(), "apikey": api_key}
    url = "https://financialmodelingprep.com/stable/economic-calendar?" + urllib.parse.urlencode(params)
    print(f"[collector] Fetching: {url.replace(api_key, '***')}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and "Error" in str(data):
            raise ValueError(f"FMP error: {data}")
        print(f"[collector] FMP returned {len(data)} events")
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"[collector] HTTP {e.code}: {body[:300]}")
        return []
    except Exception as e:
        print(f"[collector] Error: {e}")
        return []


def classify_event(event_name: str) -> tuple:
    """Vraca (indicator_type, impact) ili (None, None)."""
    name = event_name.lower()
    for required, excludes, itype, impact in INDICATOR_MAP:
        if required not in name:
            continue
        if any(ex in name for ex in excludes):
            continue
        return itype, impact
    return None, None


def parse_country_to_ccy(item: dict) -> str | None:
    country = (item.get("country") or "").upper().strip()
    for ccy, countries in CURRENCY_COUNTRIES.items():
        if country in [c.upper() for c in countries]:
            return ccy
    return None


def to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(",", "")
    if s in ("", "-", "—", "N/A"):
        return None
    mult = 1.0
    if s.upper().endswith("K"):
        mult, s = 1_000.0, s[:-1]
    elif s.upper().endswith("M"):
        mult, s = 1_000_000.0, s[:-1]
    elif s.upper().endswith("B"):
        mult, s = 1_000_000_000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def compute_surprise(actual, forecast, previous, itype: str) -> float | None:
    ref = forecast if forecast is not None else previous
    if actual is None or ref is None:
        return None
    diff = actual - ref
    if itype in ("EMPLOYMENT", "NFP", "ADP"):
        return round(diff / abs(ref), 4) if ref != 0 else None
    return round(diff, 4)


def collect(as_of: str | None = None) -> dict:
    """
    Povlaci makro podatke i bira najrelevantniji event po (valuta, indikator).

    as_of: ako je zadat (YYYY-MM-DD), koristi se samo za istorijsku
           rekonstrukciju — filtrira event-e na release_date <= as_of
           (kao da je taj dan "danas"). None = normalno ponasanje (zakljucano V1).
    """
    if not FMP_API_KEY:
        raise ValueError("FMP_API_KEY nije postavljen.")

    raw_events = fetch_calendar(FMP_API_KEY, DAYS_BACK)
    if not raw_events:
        return {}

    latest: dict[str, dict[str, dict]] = {ccy: {} for ccy in CURRENCY_COUNTRIES}
    # Pratimo preferred score za svaki (ccy, itype) da uzmemo najrelevantniji event
    scores: dict[str, dict[str, int]] = {ccy: {} for ccy in CURRENCY_COUNTRIES}

    for ev in raw_events:
        ccy = parse_country_to_ccy(ev)
        if not ccy:
            continue

        itype, impact = classify_event(ev.get("event", ""))
        if not itype:
            continue

        release_date = (ev.get("date") or "")[:10]
        # As-of filter: preskoci event-e objavljene POSLE ciljnog datuma
        if as_of is not None and release_date and release_date > as_of:
            continue

        actual   = to_float(ev.get("actual"))
        forecast = to_float(ev.get("estimate") or ev.get("forecast"))
        previous = to_float(ev.get("previous"))

        if actual is None:
            continue

        surprise = compute_surprise(actual, forecast, previous, itype)

        record = {
            "actual":        actual,
            "forecast":      forecast,
            "previous":      previous,
            "surprise_diff": surprise,
            "event_name":    ev.get("event", ""),
            "release_date":  release_date,
            "impact":        impact,
        }

        event_name = ev.get("event", "")
        pref = preferred_score(event_name, itype, ccy)
        existing = latest[ccy].get(itype)
        existing_pref = scores[ccy].get(itype, -1)
        existing_date = existing["release_date"] if existing else ""

        if existing is None:
            # Nema niceg — uzmi ovo
            latest[ccy][itype] = record
            scores[ccy][itype] = pref
        elif pref > existing_pref:
            # Bolji preferred match — zameni bez obzira na datum
            latest[ccy][itype] = record
            scores[ccy][itype] = pref
        elif pref == existing_pref and release_date > existing_date:
            # Isti prioritet — uzmi noviji datum
            latest[ccy][itype] = record

    for ccy, indicators in latest.items():
        if indicators:
            gdp_info = f" [GDP: {indicators['GDP']['event_name']}]" if 'GDP' in indicators else ""
            print(f"[collector] {ccy}: {len(indicators)} — {', '.join(indicators.keys())}{gdp_info}")

    return latest


def save_raw(data: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "macro_raw.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "daysBack": DAYS_BACK,
            "data": data,
        }, f, indent=2, ensure_ascii=False)
    print(f"[collector] Saved → {out}")


if __name__ == "__main__":
    result = collect()
    save_raw(result)
