"""
cot_model_test.py
Poredi TRI COT modela na ISTIM istorijskim podacima:

  1. LEGACY      — Non-Commercial (ono sto CME sada koristi)
  2. LEV FUNDS   — Leveraged Funds iz TFF (hedge fondovi, brzi novac)
  3. ASSET MGRS  — Asset Managers iz TFF (penzioni/institucionalni, spori novac)

Meri (sto je Luka trazio):
  - korelacija sa kretanjem cene (Pearson, na 1/4/12 nedelja unapred)
  - broj/procenat uspesnih signala (hit rate)
  - prosecna RANOST signala (na kom lag-u je korelacija najjaca)
  - koliko se cesto LF i AM medjusobno RAZILAZE

VAZNO — inverzija:
  CME valutni futures su svi kotirani kao XXX/USD. JPY futures rastu kad
  USDJPY PADA. Isto CHF i CAD. Bez inverzije bi ta tri izgledala kao da
  COT sistematski gresi. Mapa ispod to resava (invert=True).

Signal je definisan ISTO za sva tri modela (fer poredjenje):
  deltaPct6w = longPct(t) - longPct(t-6 nedelja)     <- isto sto CME radi
  longPct = long / (long + short)  za datu kategoriju

Pokreni:
  cd /d "D:\\Firefox\\CME"
  python cot_model_test.py            # svih 8 valuta
  python cot_model_test.py EUR        # samo jedna
"""
import os
import sys
import json
import math
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path



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




# ── Ispis ide i na ekran i u fajl ────────────────────────────
# Razlog: ako se skript pokrene dvoklikom, prozor se zatvori cim zavrsi i
# ne stignes nista da procitas. Ovako uvek ostane cot_model_test_output.txt.
class _Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")
        self.term = sys.__stdout__
    def write(self, x):
        try: self.term.write(x)
        except Exception: pass
        self.f.write(x)
    def flush(self):
        try: self.term.flush()
        except Exception: pass
        self.f.flush()

_OUT_PATH = str(Path(__file__).parent / "cot_model_test_output.txt")

FMP_KEY = _load_fmp_key()
SOCRATA = "https://publicreporting.cftc.gov/resource"
LEGACY_DS = "6dca-aqww"   # Legacy Futures Only  (ono sto CME sad koristi)
TFF_DS    = "gpe5-46if"   # TFF Futures Only     (dealer/asset mgr/lev money)

WEEKS = 160          # ~3 godine COT istorije
DELTA_WINDOW = 6     # nedelja — isto kao CME deltaPct6w
FWD_HORIZONS = [1, 4, 12]   # nedelja unapred za merenje ishoda
SIGNAL_MIN = 5.0     # |delta| >= 5pp da se racuna kao signal (ne sum)
MAX_LAG = 8          # do koliko nedelja unazad trazimo "ranost"

# ccy -> (cftc kod, FMP simbol, invert?)
#   invert=True  -> futures rastu kad par pada (XXX je quote valuta u paru)
MARKETS = {
    "EUR": ("099741", "EURUSD", False),
    "GBP": ("096742", "GBPUSD", False),
    "AUD": ("232741", "AUDUSD", False),
    "NZD": ("112741", "NZDUSD", False),
    "JPY": ("097741", "USDJPY", True),   # JPY futures ~ 1/USDJPY
    "CHF": ("092741", "USDCHF", True),   # CHF futures ~ 1/USDCHF
    "CAD": ("090741", "USDCAD", True),   # CAD futures ~ 1/USDCAD
    "USD": ("098662", "DXY",    False),  # USD Index — mozda ne radi na planu
}


# ────────────────────────── HTTP ──────────────────────────
def _get(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_err": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:80]}"}
    except Exception as e:
        return {"_err": str(e)}


def fetch_cot(dataset, code, fields):
    params = {
        "cftc_contract_market_code": code,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(WEEKS),
        "$select": "report_date_as_yyyy_mm_dd," + ",".join(fields),
    }
    d = _get(f"{SOCRATA}/{dataset}.json?" + urllib.parse.urlencode(params))
    if isinstance(d, dict):
        print(f"    greska: {d.get('_err')}")
        return []
    return d


def fetch_prices(symbol):
    """Vraca {date(str): close}. Proba vise FMP ruta jer ne znamo plan."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=int(WEEKS * 7 * 1.15))
    routes = [
        ("stable/historical-price-eod/full",
         {"symbol": symbol, "from": start.isoformat(), "to": today.isoformat()}),
        ("stable/historical-price-eod/light",
         {"symbol": symbol, "from": start.isoformat(), "to": today.isoformat()}),
        (f"api/v3/historical-price-full/{symbol}",
         {"from": start.isoformat(), "to": today.isoformat()}),
    ]
    for path, p in routes:
        p = dict(p); p["apikey"] = FMP_KEY
        d = _get("https://financialmodelingprep.com/" + path + "?" + urllib.parse.urlencode(p))
        rows = None
        if isinstance(d, list) and d:
            rows = d
        elif isinstance(d, dict) and isinstance(d.get("historical"), list):
            rows = d["historical"]
        if rows:
            out = {}
            for r in rows:
                dt = (r.get("date") or "")[:10]
                c = r.get("close") if r.get("close") is not None else r.get("price")
                if dt and c is not None:
                    try: out[dt] = float(c)
                    except (TypeError, ValueError): pass
            if out:
                return out, path
    return None, None


# ────────────────────── matematika ──────────────────────
def pearson(xs, ys):
    n = len(xs)
    if n < 8: return None
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    if dx == 0 or dy == 0: return None
    return num / (dx*dy)


def long_pct(l, s):
    t = l + s
    return (l / t * 100) if t > 0 else None


def price_near(prices, date_str, offset_days=0):
    """Cena na datum (ili prvi prethodni radni dan unazad, do 6 dana)."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date() + timedelta(days=offset_days)
    for back in range(7):
        k = (d - timedelta(days=back)).isoformat()
        if k in prices:
            return prices[k]
    return None


def build_series(ccy):
    """Vraca [{date, legacy, lf, am}] sortirano ASC, sa longPct po modelu."""
    code, _, _ = MARKETS[ccy]
    leg = fetch_cot(LEGACY_DS, code,
                    ["noncomm_positions_long_all", "noncomm_positions_short_all"])
    tff = fetch_cot(TFF_DS, code,
                    ["lev_money_positions_long", "lev_money_positions_short",
                     "asset_mgr_positions_long", "asset_mgr_positions_short"])
    if not leg or not tff:
        return []
    L = {}
    for r in leg:
        d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        try:
            L[d] = long_pct(float(r["noncomm_positions_long_all"]),
                            float(r["noncomm_positions_short_all"]))
        except (KeyError, TypeError, ValueError): pass
    T = {}
    for r in tff:
        d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        try:
            T[d] = (long_pct(float(r["lev_money_positions_long"]),
                             float(r["lev_money_positions_short"])),
                    long_pct(float(r["asset_mgr_positions_long"]),
                             float(r["asset_mgr_positions_short"])))
        except (KeyError, TypeError, ValueError): pass

    out = []
    for d in sorted(set(L) & set(T)):
        lf, am = T[d]
        if L[d] is None or lf is None or am is None: continue
        out.append({"date": d, "legacy": L[d], "lf": lf, "am": am})
    return out


def analyze(ccy, series, prices, invert):
    """Vraca metrike po modelu + divergenciju LF vs AM."""
    res = {m: {"corr": {}, "hits": 0, "signals": 0, "lag_corr": []}
           for m in ("legacy", "lf", "am")}
    rows = []
    for i in range(DELTA_WINDOW, len(series)):
        cur, past = series[i], series[i-DELTA_WINDOW]
        p0 = price_near(prices, cur["date"])
        if p0 is None: continue
        fwd = {}
        for h in FWD_HORIZONS:
            p1 = price_near(prices, cur["date"], h*7)
            if p1 is not None:
                r = (p1 - p0) / p0 * 100
                fwd[h] = -r if invert else r   # inverzija: futures vs par
        if not fwd: continue
        rows.append({
            "date": cur["date"],
            "d": {m: cur[m] - past[m] for m in ("legacy", "lf", "am")},
            "fwd": fwd,
        })
    if len(rows) < 20:
        return None, len(rows)

    for m in ("legacy", "lf", "am"):
        for h in FWD_HORIZONS:
            xs = [r["d"][m] for r in rows if h in r["fwd"]]
            ys = [r["fwd"][h] for r in rows if h in r["fwd"]]
            c = pearson(xs, ys)
            if c is not None: res[m]["corr"][h] = c
        # hit rate na 4w (srednji horizont), samo pravi signali
        H = 4
        sig = [r for r in rows if H in r["fwd"] and abs(r["d"][m]) >= SIGNAL_MIN]
        res[m]["signals"] = len(sig)
        res[m]["hits"] = sum(1 for r in sig
                             if (r["d"][m] > 0) == (r["fwd"][H] > 0))
        # ranost: korelacija delta(t) sa 4w prinosom na razlicitim lag-ovima
        for lag in range(0, MAX_LAG+1):
            xs, ys = [], []
            for i2 in range(len(rows)-lag):
                if H in rows[i2+lag]["fwd"]:
                    xs.append(rows[i2]["d"][m]); ys.append(rows[i2+lag]["fwd"][H])
            c = pearson(xs, ys)
            res[m]["lag_corr"].append((lag, c if c is not None else 0.0))

    # divergencija LF vs AM — koliko cesto suprotan smer (oba iznad praga)
    both = [r for r in rows if abs(r["d"]["lf"]) >= SIGNAL_MIN
                            and abs(r["d"]["am"]) >= SIGNAL_MIN]
    div = sum(1 for r in both if (r["d"]["lf"] > 0) != (r["d"]["am"] > 0))
    res["_div"] = (div, len(both))
    return res, len(rows)


# ────────────────────────── main ──────────────────────────
def main():
    if not FMP_KEY:
        print("FMP kljuc nije nadjen ni u okruzenju ni u run_cme.bat.")
        print("Proveri da u run_cme.bat postoji red:  set FMP_API_KEY=tvoj_kljuc")
        sys.exit(1)

    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    ccys = [only] if only else list(MARKETS)
    if only and only not in MARKETS:
        print(f"Nepoznata valuta {only}. Dostupne: {list(MARKETS)}"); sys.exit(1)

    print(f"COT MODEL TEST — {WEEKS} nedelja, signal = delta{DELTA_WINDOW}w, "
          f"prag {SIGNAL_MIN}pp\n")
    summary = []
    for ccy in ccys:
        code, sym, invert = MARKETS[ccy]
        print(f"── {ccy} ({sym}{' INVERTOVAN' if invert else ''}) ──")
        series = build_series(ccy)
        if not series:
            print("   nema COT podataka\n"); continue
        prices, route = fetch_prices(sym)
        if not prices:
            print(f"   ❌ nema cena za {sym} — preskacem "
                  f"(FMP plan mozda nema forex istoriju)\n"); continue
        print(f"   COT {len(series)} ned. | cene {len(prices)} dana (ruta: {route})")

        res, n = analyze(ccy, series, prices, invert)
        if res is None:
            print(f"   premalo poklopljenih tacaka ({n})\n"); continue

        print(f"   {'model':<10}{'corr1w':>8}{'corr4w':>8}{'corr12w':>9}"
              f"{'hit@4w':>9}{'signala':>9}{'ranost':>8}")
        for m, label in (("legacy", "LEGACY"), ("lf", "LEV FUNDS"), ("am", "ASSET MGR")):
            r = res[m]
            c = lambda h: f"{r['corr'][h]:+.2f}" if h in r["corr"] else "  —"
            hit = f"{r['hits']}/{r['signals']}" if r["signals"] else "—"
            hitpct = f" ({r['hits']/r['signals']*100:.0f}%)" if r["signals"] else ""
            best = max(r["lag_corr"], key=lambda t: abs(t[1]))[0] if r["lag_corr"] else "—"
            print(f"   {label:<10}{c(1):>8}{c(4):>8}{c(12):>9}"
                  f"{hit:>9}{hitpct:<6}{best:>4}w")
        dv, dt = res["_div"]
        dpct = (dv/dt*100) if dt else 0
        print(f"   LF vs AM razilazenje: {dv}/{dt} nedelja ({dpct:.0f}%)\n")
        summary.append((ccy, res, dpct))

    if len(summary) > 1:
        print("=" * 64)
        print("ZBIRNO (hit rate @4w, sve valute)")
        print("=" * 64)
        for m, label in (("legacy", "LEGACY"), ("lf", "LEV FUNDS"), ("am", "ASSET MGR")):
            h = sum(r[m]["hits"] for _, r, _ in summary)
            s = sum(r[m]["signals"] for _, r, _ in summary)
            cs = [r[m]["corr"].get(4) for _, r, _ in summary if 4 in r[m]["corr"]]
            avgc = sum(cs)/len(cs) if cs else 0
            print(f"  {label:<10} hit {h}/{s} "
                  f"({h/s*100 if s else 0:.1f}%)   prosecna corr4w {avgc:+.3f}")
        avgdiv = sum(d for _, _, d in summary)/len(summary)
        print(f"\n  LF vs AM razilazenje, prosek: {avgdiv:.0f}% nedelja")
        print("""
  Kako citati:
   - corr = Pearson izmedju delta6w i prinosa unapred. Veci |broj| = jaci odnos.
     POZITIVAN = COT smer prati cenu (potvrdni). NEGATIVAN = kontrarian.
   - hit@4w = koliko puta je smer signala pogodio smer cene za 4 nedelje.
     ~50% = nasumicno. Znacajno iznad = model ima informaciju.
   - ranost = lag (nedelja) gde je korelacija najjaca. 0w = istovremeno,
     veci broj = model se okrece PRE cene.
   - razilazenje = koliko cesto LF i AM idu u suprotnim smerovima. Visoko
     razilazenje znaci da ih Legacy sabija u kasu i gubi informaciju.
""")


if __name__ == "__main__":
    _tee = _Tee(_OUT_PATH)
    sys.stdout = _tee
    try:
        main()
    except KeyboardInterrupt:
        print("\n[prekinuto]")
    except Exception:
        import traceback
        print("\n" + "=" * 64)
        print("GRESKA — ceo trag:")
        print("=" * 64)
        traceback.print_exc(file=_tee)
    finally:
        print(f"\n[ispis sacuvan u: {_OUT_PATH}]")
        sys.stdout = sys.__stdout__
        _tee.flush()
        try:
            input("\nPritisni Enter za zatvaranje...")
        except Exception:
            pass
