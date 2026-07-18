"""
yield_collector.py
Povlaci Treasury prinose sa FMP stable/treasury-rates i racuna
trend 2Y prinosa (za Gold Macro engine).

2Y yield rising = hawkish = BEARISH za zlato.
2Y yield falling = dovish = BULLISH za zlato.

Signal se racuna kao promena preko prozora (default 20 radnih dana ~ 1 mesec).
Prag je konfigurabilan (u indicator_config.py: YIELD_TREND_THRESHOLD).
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"
FMP_API_KEY = ""  # postavlja se dinamički

# Prag promene 2Y prinosa (u procentnim poenima) da bi trend bio znacajan.
# Kalibrisano konzervativno: 0.10pp preko prozora = znacajan pomak.
# Menjaj u indicator_config.py ako zatreba (importuje se tamo).
DEFAULT_YIELD_THRESHOLD = 0.10
TREND_WINDOW_DAYS = 30   # kalendarskih dana unazad za trend


def fetch_treasury(api_key: str = "", days_back: int = 40) -> list[dict]:
    key = api_key or FMP_API_KEY or os.environ.get("FMP_API_KEY", "")
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days_back)
    params = {
        "from": start.isoformat(),
        "to": today.isoformat(),
        "apikey": key,
    }
    url = "https://financialmodelingprep.com/stable/treasury-rates?" + \
          urllib.parse.urlencode(params)
    print(f"[yield] Fetching treasury rates...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list) or not data:
            print(f"[yield] Neocekivan odgovor: {str(data)[:150]}")
            return []
        return data
    except urllib.error.HTTPError as e:
        print(f"[yield] HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:150]}")
        return []
    except Exception as e:
        print(f"[yield] Greska: {e}")
        return []


def compute_2y_trend(rows: list[dict], threshold: float = DEFAULT_YIELD_THRESHOLD) -> dict | None:
    """
    Racuna trend 2Y prinosa.
    rows: lista dnevnih zapisa (FMP vraca DESC — najnoviji prvi).
    Vraca dict sa: current, past, change, signal ('rising'|'falling'|'flat'),
    goldSignal ('bullish'|'bearish'|'neutral').
    """
    # Filtriraj zapise koji imaju year2
    valid = [r for r in rows if r.get("year2") is not None]
    if len(valid) < 2:
        return None

    # FMP vraca DESC (najnoviji prvi)
    valid.sort(key=lambda r: r.get("date", ""), reverse=True)
    current_row = valid[0]
    past_row = valid[-1]

    try:
        current = float(current_row["year2"])
        past = float(past_row["year2"])
    except (ValueError, TypeError, KeyError):
        return None

    change = round(current - past, 3)

    if change > threshold:
        yield_signal = "rising"
        gold_signal = "bearish"   # hawkish -> bearish gold
    elif change < -threshold:
        yield_signal = "falling"
        gold_signal = "bullish"   # dovish -> bullish gold
    else:
        yield_signal = "flat"
        gold_signal = "neutral"

    return {
        "current":     current,
        "past":        past,
        "change":      change,
        "threshold":   threshold,
        "yieldSignal": yield_signal,
        "goldSignal":  gold_signal,
        "currentDate": current_row.get("date", ""),
        "pastDate":    past_row.get("date", ""),
        # Bonus: cela kriva za buduci prikaz
        "curve": {
            "3M":  current_row.get("month3"),
            "2Y":  current_row.get("year2"),
            "10Y": current_row.get("year10"),
            "30Y": current_row.get("year30"),
        },
    }


def collect(threshold: float = DEFAULT_YIELD_THRESHOLD) -> dict | None:
    key = FMP_API_KEY or os.environ.get("FMP_API_KEY", "")
    if not key:
        print("[yield] FMP_API_KEY nije postavljen — preskacem yield.")
        return None
    rows = fetch_treasury(key)
    if not rows:
        return None
    trend = compute_2y_trend(rows, threshold)
    if trend is None:
        print("[yield] Nedovoljno podataka za 2Y trend.")
        return None
    print(f"[yield] 2Y: {trend['past']} -> {trend['current']} "
          f"(change {trend['change']:+.3f}pp, {trend['yieldSignal']}) "
          f"=> Gold {trend['goldSignal']} "
          f"[{trend['pastDate']} .. {trend['currentDate']}]")
    return trend


if __name__ == "__main__":
    result = collect()
    if result:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DIR / "yield_debug.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"[yield] Saved debug -> {OUTPUT_DIR / 'yield_debug.json'}")
