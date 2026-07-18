"""
CME News Updater
Povlaci High impact ekonomske vesti sa FMP Economic Calendar API-ja
za poslednjih 7 dana, racuna surprise + impulse (sa decay-om), i
upisuje rezultat u news.json. cme.html nikad se ne menja.

Pokrece se preko run_cme.bat
"""

import sys
import os
import json
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.parse
import urllib.error

# ──────────────────────────────────────────────────────────
# CONFIG — menja se iz .bat fajla preko env varijabli
# ──────────────────────────────────────────────────────────
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
JSON_PATH = os.environ.get("CME_JSON_PATH", "news.json")
DAYS_BACK = int(os.environ.get("CME_DAYS_BACK", "7"))

TRACKED_CCY = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}

EVENT_TYPE_MAP = [
    ("gdp", "GDP"),
    ("retail sales", "RETAIL_SALES"),
    ("hicp", "HICP_YOY"),
    ("cpi", "CPI_YOY"),
    ("ppi", "PPI_YOY"),
    ("pmi", "PMI"),
    ("unemployment rate", "UNEMPLOYMENT"),
    ("non farm payroll", "EMPLOYMENT"),
    ("nonfarm payroll", "EMPLOYMENT"),
    ("employment change", "EMPLOYMENT"),
    ("adp", "EMPLOYMENT"),
]

# Pragovi za "stvarno iznenadjenje" po tipu vesti
NEWS_THRESHOLDS = {
    "GDP": 0.2, "RETAIL_SALES": 0.2,
    "CPI_YOY": 0.2, "PPI_YOY": 0.2, "HICP_YOY": 0.2,
    "CPI_MOM": 0.1, "PPI_MOM": 0.1, "HICP_MOM": 0.1,
    "PMI": 0.3,
    "UNEMPLOYMENT": 0.1,
    "EMPLOYMENT": 0.10,  # relativni prag (% od forecast)
}
INVERTED_TYPES = {"UNEMPLOYMENT"}  # vesti gde "vise" = bearish za valutu


def classify_event(event_name: str):
    name = event_name.lower()
    is_mom = "(mom)" in name or " mom" in name
    for key, base_type in EVENT_TYPE_MAP:
        if key in name:
            if base_type in ("CPI_YOY", "PPI_YOY", "HICP_YOY") and is_mom:
                return base_type.replace("_YOY", "_MOM")
            return base_type
    return None


def fetch_fmp_calendar(api_key: str, days_back: int):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days_back)
    params = {"from": start.isoformat(), "to": today.isoformat(), "apikey": api_key}
    # FMP stable endpoint (v3/economic_calendar je deprecated)
    url = "https://financialmodelingprep.com/stable/economic-calendar?" + urllib.parse.urlencode(params)
    print(f"[fetch] {url.replace(api_key, '***')}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("Error Message"):
            print(f"[error] FMP API error: {data['Error Message']}")
            return []
        if isinstance(data, dict) and not data.get("news") and "Error" in str(data):
            print(f"[error] Unexpected response: {data}")
            return []
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"[error] HTTP {e.code}: {body[:300]}")
        return []
    except Exception as e:
        print(f"[error] Failed to fetch FMP calendar: {e}")
        return []


def parse_currency(item: dict):
    ccy = item.get("currency")
    if ccy and ccy.upper() in TRACKED_CCY:
        return ccy.upper()
    country = (item.get("country") or "").upper()
    country_to_ccy = {
        "US": "USD", "USA": "USD",
        "EU": "EUR", "EMU": "EUR", "EUR": "EUR", "GERMANY": "EUR", "ITALY": "EUR", "FRANCE": "EUR",
        "UK": "GBP", "GB": "GBP",
        "JP": "JPY", "JAPAN": "JPY",
        "CH": "CHF", "SWITZERLAND": "CHF",
        "CA": "CAD", "CANADA": "CAD",
        "AU": "AUD", "AUSTRALIA": "AUD",
        "NZ": "NZD", "NEW ZEALAND": "NZD",
    }
    return country_to_ccy.get(country)


def days_ago(date_str: str) -> int:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "")).date()
    except Exception:
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except Exception:
            return 99
    return (datetime.now(timezone.utc).date() - dt).days


def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(",", "")
    if s in ("", "-", "—"):
        return None
    multiplier = 1.0
    if s.upper().endswith("K"):
        multiplier, s = 1000.0, s[:-1]
    elif s.upper().endswith("M"):
        multiplier, s = 1_000_000.0, s[:-1]
    elif s.upper().endswith("B"):
        multiplier, s = 1_000_000_000.0, s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def news_decay(d_ago: int) -> float:
    if d_ago <= 0:
        return 1.0
    if d_ago == 1:
        return 0.75
    if d_ago == 2:
        return 0.50
    if d_ago == 3:
        return 0.25
    return 0.0


def compute_impulse(event_type: str, actual: float, forecast, previous, impact: str):
    """Vraca (impulse_bez_decay, surprise_diff) ili (None, None) ako nema znacajnog iznenadjenja."""
    ref = forecast if forecast is not None else previous
    if ref is None:
        return None, None

    diff = actual - ref
    threshold = NEWS_THRESHOLDS.get(event_type, 0.2)

    if event_type == "EMPLOYMENT":
        normalized = diff / abs(ref) if ref != 0 else 0
        if abs(normalized) < threshold:
            return None, None
    else:
        if abs(diff) < threshold:
            return None, None
        normalized = diff / threshold

    direction = 1 if normalized > 0 else -1
    if event_type in INVERTED_TYPES:
        direction = -direction

    max_pts = 10 if impact.lower() == "high" else 5
    magnitude = min(1.0, abs(normalized) / 3)  # saturira posle 3x praga
    impulse = round(direction * max_pts * magnitude, 2)
    return impulse, diff


def build_news_list(raw_events: list):
    news = []
    for ev in raw_events:
        impact = (ev.get("impact") or "").lower()
        if impact != "high":
            continue

        ccy = parse_currency(ev)
        if not ccy:
            continue

        event_type = classify_event(ev.get("event", ""))
        if not event_type:
            continue

        actual = to_float(ev.get("actual"))
        forecast = to_float(ev.get("estimate") if "estimate" in ev else ev.get("forecast"))
        previous = to_float(ev.get("previous"))
        if actual is None:
            continue

        d_ago = days_ago(ev.get("date", ""))
        if d_ago < 0 or d_ago > 3:
            continue

        impulse_base, diff = compute_impulse(event_type, actual, forecast, previous, impact)
        if impulse_base is None:
            continue  # nema znacajnog iznenadjenja, ne ukljucuj

        decay = news_decay(d_ago)
        impulse_now = round(impulse_base * decay, 2)

        news.append({
            "ccy": ccy,
            "type": event_type,
            "eventName": ev.get("event", ""),
            "impact": "high",
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "date": ev.get("date", ""),
            "daysAgo": d_ago,
            "surpriseDiff": round(diff, 3),
            "impulseBase": impulse_base,   # impulse na dan objave (decay=1.0)
            "impulse": impulse_now,         # impulse SADA, nakon decay-a
            "decay": decay,
        })
    return news


def write_news_json(news: list, json_path: str):
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "daysBack": DAYS_BACK,
        "news": news,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[ok] Sacuvano {len(news)} vesti u {json_path}")


def main():
    if not FMP_API_KEY:
        print("[error] FMP_API_KEY nije postavljen. Pokreni preko run_cme.bat")
        sys.exit(1)

    print(f"[info] Povlacim FMP economic calendar (zadnjih {DAYS_BACK} dana, samo High impact)...")
    raw = fetch_fmp_calendar(FMP_API_KEY, DAYS_BACK)
    print(f"[info] FMP vratio {len(raw)} ukupnih dogadjaja.")

    news = build_news_list(raw)
    print(f"[info] Posle filtriranja (High impact, pratimo, znacajno iznenadjenje, decay<=3d): {len(news)} vesti.")
    for n in news:
        print(f"   - {n['ccy']} {n['type']}: actual={n['actual']} forecast={n['forecast']} "
              f"diff={n['surpriseDiff']} impulse_now={n['impulse']} ({n['daysAgo']}d ago, decay={n['decay']}) "
              f":: {n['eventName']}")

    write_news_json(news, JSON_PATH)
    print("[done] Otvori cme.html u browseru — ucitace news.json automatski.")


if __name__ == "__main__":
    main()

