"""
intermarket_probe.py
Proverava STA je dostupno na tvom FMP planu za Intermarket modul.
Ne gradimo nista dok ne znamo sta izvor stvarno daje.

Intermarket treba 3 grupe podataka:
  1. 2Y TRZISNI prinosi po zemlji (US, CA, AU, NZ, DE/EUR, UK, JP, CH)
     -> za diferencijal prinosa
     NAPOMENA: ovo je trzisni prinos, NE politicka stopa CB
     (politicka stopa je vec u Heatmap-u kao INTEREST_RATE -> ne dupliramo)
  2. Korelisana trzista: nafta (CAD), bakar (AUD), zlato (CHF)
  3. Risk rezim: VIX, S&P 500

Pokreni:
  cd /d "D:\\Firefox\\CME"
  python intermarket_probe.py
(FMP_API_KEY se cita iz okruzenja — run_cme.bat ga vec postavlja)
"""
import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone



def _load_fmp_key():
    import re as _re
    from pathlib import Path as _P
    k = os.environ.get("FMP_API_KEY", "")
    if k and not k.startswith("UPISI"):
        return k
    # keys.bat prvo (kljucevi zive tamo), run_cme.bat kao rezerva za stari setup
    for fname in ("keys.bat", "run_cme.bat"):
        f = _P(__file__).parent / fname
        if not f.exists():
            continue
        try:
            m = _re.search(r"(?im)^\s*set\s+FMP_API_KEY\s*=\s*(\S+)",
                           f.read_text(encoding="utf-8", errors="ignore"))
            if m:
                k = m.group(1).strip()
                if k and not k.startswith("UPISI"):
                    print(f"[key] Kljuc procitan iz {fname}")
                    return k
        except Exception:
            pass
    return ""


API_KEY = _load_fmp_key()
if not API_KEY:
    print("FMP kljuc nije nadjen ni u okruzenju ni u run_cme.bat.")
    print("Proveri da u run_cme.bat postoji red:  set FMP_API_KEY=tvoj_kljuc")
    raise SystemExit(1)

BASE = "https://financialmodelingprep.com"
today = datetime.now(timezone.utc).date()
start = today - timedelta(days=40)


def probe(label, path, params=None, show_keys=True, sample=1):
    """Pozovi endpoint i prijavi da li radi + kako izgleda odgovor."""
    p = dict(params or {})
    p["apikey"] = API_KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(p)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:90]
        print(f"  [{label:22}] HTTP {e.code}: {body}")
        return None
    except Exception as e:
        print(f"  [{label:22}] GRESKA: {e}")
        return None

    if isinstance(data, dict) and ("Error Message" in data or "message" in data):
        print(f"  [{label:22}] ODBIJEN: {str(data)[:90]}")
        return None
    if not data:
        print(f"  [{label:22}] PRAZAN odgovor")
        return None

    first = data[0] if isinstance(data, list) else data
    print(f"  [{label:22}] ✅ OK")
    if show_keys and isinstance(first, dict):
        keys = list(first.keys())
        print(f"  {'':24} polja: {keys[:9]}{'…' if len(keys) > 9 else ''}")
    if sample and isinstance(data, list):
        for row in data[:sample]:
            print(f"  {'':24} {json.dumps(row, ensure_ascii=False)[:150]}")
    return data


print("=" * 74)
print("1) 2Y TRZISNI PRINOSI  (za diferencijal — ovo NIJE politicka CB stopa)")
print("=" * 74)
print("\n-- US (znamo da radi, referenca) --")
probe("US treasury-rates", "stable/treasury-rates",
      {"from": start.isoformat(), "to": today.isoformat()})

print("\n-- Ne-US prinosi: probamo vise ruta --")
# Ruta A: FMP economics/market indices za obveznice
for label, sym in [
    ("DE 2Y (Bund)", "^DE2Y"), ("UK 2Y (Gilt)", "^GB2Y"),
    ("JP 2Y (JGB)",  "^JP2Y"), ("CA 2Y",        "^CA2Y"),
    ("AU 2Y",        "^AU2Y"),
]:
    probe(label, "stable/quote", {"symbol": sym}, show_keys=False)

# Ruta B: economic indicator endpoint
probe("economic-indicators", "stable/economic-indicators",
      {"name": "GDP"}, sample=1)

# Ruta C: ETF-ovi kao proxy za prinose (ako nema direktnih)
print("\n-- ETF proxy (ako direktni prinosi ne rade) --")
for label, sym in [("SHY US 1-3Y ETF", "SHY"), ("IEF US 7-10Y ETF", "IEF")]:
    probe(label, "stable/quote", {"symbol": sym}, show_keys=False)

print()
print("=" * 74)
print("2) KORELISANA TRZISTA  (nafta->CAD, bakar->AUD, zlato->CHF)")
print("=" * 74)
for label, sym in [
    ("WTI nafta",     "CLUSD"), ("Brent nafta", "BZUSD"),
    ("Bakar",         "HGUSD"), ("Zlato",       "GCUSD"),
    ("WTI (alt)",     "WTIUSD"),
]:
    probe(label, "stable/quote", {"symbol": sym}, show_keys=False)

print("\n-- commodities lista (da vidimo tacne simbole) --")
cl = probe("commodities-list", "stable/commodities-list", show_keys=False, sample=0)
if cl:
    syms = [c.get("symbol") for c in cl if isinstance(c, dict)]
    want = [s for s in syms if any(k in str(s).upper()
            for k in ("CL", "BZ", "HG", "GC", "WTI", "COPPER", "BRENT"))]
    print(f"  {'':24} interesantni: {want[:14]}")

print()
print("=" * 74)
print("3) RISK REZIM  (VIX, S&P)")
print("=" * 74)
for label, sym in [("VIX", "^VIX"), ("S&P 500", "^GSPC"), ("SPY ETF", "SPY")]:
    probe(label, "stable/quote", {"symbol": sym}, show_keys=False)

print()
print("=" * 74)
print("REZIME — sta gledamo:")
print("=" * 74)
print("""
  ✅ US treasury radi (znamo od ranije)
  ? Ne-US 2Y prinosi — ako NIJEDNA ruta ne radi, diferencijal prinosa
    ne moze da se napravi na ovom planu. Tada Intermarket ide bez njega
    (nafta/bakar/zlato + risk rezim), ili trazimo drugi izvor.
  ? Robe i indeksi — verovatno rade; treba nam tacan format simbola.

  Posalji ceo ispis.
""")
