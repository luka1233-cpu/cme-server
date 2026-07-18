"""
cot_validation_test.py
Tri validaciona testa posle nalaza da je COT delta6w anti-prediktivan.

TEST A — STVARNI CME COT BLOK (ne sirovi delta6w)
  scoreCOT(delta) je samo clamp(delta*2, ±40) — znak mu je ISTI kao delti,
  pa bi test samo njega dao identicne brojeve. ALI scoreWeekly moze da ide
  PROTIV delte (kad se nedeljni tok ne slaze sa 6w trendom, bodovi idu u
  nedeljnom smeru). Zato testiramo CEO blok: cotMom + tq + weekly — ono
  sto CME stvarno koristi.

TEST B — WALK-FORWARD (dve polovine)
  Deli istoriju na stariju i noviju polovinu. Ako efekat drzi u OBE,
  nije rezim nego prava osobina. Ako je samo u jednoj — artefakt.

TEST C — PERCENTIL / EKSTREMI
  Klasicna COT literatura kaze da COT radi na EKSTREMIMA, ne na smeru
  trenda. Testiramo: percentil >95 (prenatrpano long) i <5 (prenatrpano
  short) — da li ekstrem daje bolji edge nego smer.
  Percentil je ROLLING: u svakoj nedelji racunat na osnovu prethodne
  3 godine (bez gledanja u buducnost).

Pokreni:  python cot_validation_test.py
Ispis se cuva u cot_validation_output.txt
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


class _Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8"); self.term = sys.__stdout__
    def write(self, x):
        try: self.term.write(x)
        except Exception: pass
        self.f.write(x)
    def flush(self):
        try: self.term.flush()
        except Exception: pass
        self.f.flush()


FMP_KEY = _load_fmp_key()
_OUT = str(Path(__file__).parent / "cot_validation_output.txt")

SOCRATA = "https://publicreporting.cftc.gov/resource"
LEGACY_DS, TFF_DS = "6dca-aqww", "gpe5-46if"
WEEKS = 320          # ~6 godina — treba nam vise jer percentil jede 156 unazad
PCT_WINDOW = 156     # 3 godine rolling percentil
FWD = 4              # nedelja unapred (isti horizont kao prvi test)
SIGNAL_MIN = 5.0

MARKETS = {
    "EUR": ("099741", "EURUSD", False), "GBP": ("096742", "GBPUSD", False),
    "AUD": ("232741", "AUDUSD", False), "NZD": ("112741", "NZDUSD", False),
    "JPY": ("097741", "USDJPY", True),  "CHF": ("092741", "USDCHF", True),
    "CAD": ("090741", "USDCAD", True),
}
MODELS = {
    "legacy":   (LEGACY_DS, "noncomm_positions_long_all", "noncomm_positions_short_all"),
    "levFunds": (TFF_DS,    "lev_money_positions_long",   "lev_money_positions_short"),
    "assetMgr": (TFF_DS,    "asset_mgr_positions_long",   "asset_mgr_positions_short"),
}


# ── CME score funkcije — VERNO prenete iz cme.html ──
def scoreCOT(delta):    return max(-40, min(40, delta * 2))
def scoreTQ(consistent, delta):
    d = 1 if delta >= 0 else -1
    b = 5 if consistent >= 6 else 4 if consistent >= 5 else 3 if consistent >= 4 else 1 if consistent >= 3 else 0
    return d * b
def scoreWeekly(dL, dS, delta):
    net = dL - dS
    wd = 1 if net >= 0 else -1
    total = abs(dL) + abs(dS)
    if total < 1000: return 0
    pts = 30 if total >= 10000 else 20 if total >= 5000 else 10
    cd = 1 if delta >= 0 else -1
    return wd * pts if wd == cd else wd * min(pts, 10)


def _get(url, t=40):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=t) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_err": str(e)}


def fetch_cot(ds, code, fields):
    p = {"cftc_contract_market_code": code,
         "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(WEEKS),
         "$select": "report_date_as_yyyy_mm_dd," + ",".join(fields)}
    d = _get(f"{SOCRATA}/{ds}.json?" + urllib.parse.urlencode(p))
    return [] if isinstance(d, dict) else d


def fetch_prices(sym):
    today = datetime.now(timezone.utc).date()
    startd = today - timedelta(days=int(WEEKS * 7 * 1.15))
    for path in ("stable/historical-price-eod/full", "stable/historical-price-eod/light"):
        p = {"symbol": sym, "from": startd.isoformat(), "to": today.isoformat(), "apikey": FMP_KEY}
        d = _get("https://financialmodelingprep.com/" + path + "?" + urllib.parse.urlencode(p))
        rows = d if isinstance(d, list) and d else (d.get("historical") if isinstance(d, dict) else None)
        if rows:
            out = {}
            for r in rows:
                dt = (r.get("date") or "")[:10]
                c = r.get("close", r.get("price"))
                if dt and c is not None:
                    try: out[dt] = float(c)
                    except (TypeError, ValueError): pass
            if out: return out
    return None


def parse_weeks(reports, lf, sf):
    w = []
    for r in reports:
        try:
            l, s = int(float(r[lf])), int(float(r[sf]))
        except (KeyError, ValueError, TypeError): continue
        if l + s == 0: continue
        w.append({"date": (r.get("report_date_as_yyyy_mm_dd") or "")[:10],
                  "long": l, "short": s, "net": l - s, "longPct": l/(l+s)*100})
    return w


def pct_rank(vals, v):
    if len(vals) < 30: return None
    below = sum(1 for x in vals if x < v); eq = sum(1 for x in vals if x == v)
    return (below + eq/2) / len(vals) * 100


def fields_at(weeks, i):
    """CME polja kakva bi bila u nedelji i (weeks je DESC). Bez gledanja unapred."""
    if i + 6 >= len(weeks): return None
    cur, prev, w6 = weeks[i], weeks[i+1], weeks[i+6]
    delta = round(cur["longPct"] - w6["longPct"])
    od = 1 if (cur["longPct"] - w6["longPct"]) >= 0 else -1
    cons = sum(1 for k in range(i, i+6)
               if (1 if weeks[k]["longPct"] - weeks[k+1]["longPct"] >= 0 else -1) == od)
    # Percentil SAMO sa punim 3-godisnjim prozorom — inace bi najstarije tacke
    # koristile kraci prozor i ne bi bile uporedive sa novijima.
    hist = [w["net"] for w in weeks[i:i+PCT_WINDOW]]
    pct = pct_rank(hist, cur["net"]) if len(hist) >= PCT_WINDOW else None
    return {"date": cur["date"], "delta": delta,
            "dL": cur["long"] - prev["long"], "dS": cur["short"] - prev["short"],
            "tq": cons, "net": cur["net"], "pct": pct}


def price_at(prices, ds, off=0):
    d = datetime.strptime(ds, "%Y-%m-%d").date() + timedelta(days=off)
    for b in range(7):
        k = (d - timedelta(days=b)).isoformat()
        if k in prices: return prices[k]
    return None


def binom(hits, n):
    if not n: return 0.0, 1.0
    p = hits/n; z = (p-0.5)/math.sqrt(0.25/n)
    return z, math.erfc(abs(z)/math.sqrt(2))


def hitline(label, hits, n, extra=""):
    if n < 10:
        return f"  {label:<24}{'—':>18}  (premalo: {n})"
    p = hits/n*100; z, pv = binom(hits, n)
    flag = "◄ ANTI" if z < -2 else "◄ EDGE" if z > 2 else ""
    return f"  {label:<24}{hits:>4}/{n:<4}{p:>7.1f}%{z:>7.2f}σ{pv:>9.2g}  {flag}{extra}"


def main():
    if not FMP_KEY:
        print("FMP kljuc nije nadjen (ni env ni run_cme.bat)."); return

    print(f"COT VALIDACIJA — {WEEKS} ned., horizont {FWD}w, prag {SIGNAL_MIN}pp\n")

    # skupljamo sve tacke preko svih valuta
    agg = {m: {"blok": [], "delta": [], "half": {}, "ext_hi": [], "ext_lo": []}
           for m in MODELS}

    for ccy, (code, sym, inv) in MARKETS.items():
        prices = fetch_prices(sym)
        if not prices:
            print(f"── {ccy}: nema cena, preskacem"); continue

        raw_leg = fetch_cot(LEGACY_DS, code, list(MODELS["legacy"][1:]))
        raw_tff = fetch_cot(TFF_DS, code, list(MODELS["levFunds"][1:]) + list(MODELS["assetMgr"][1:]))

        for model, (ds, lf, sf) in MODELS.items():
            weeks = parse_weeks(raw_leg if model == "legacy" else raw_tff, lf, sf)
            if len(weeks) < 60: continue
            for i in range(len(weeks) - 7):
                f = fields_at(weeks, i)
                if not f: continue
                p0 = price_at(prices, f["date"])
                p1 = price_at(prices, f["date"], FWD*7)
                if p0 is None or p1 is None: continue
                ret = (p1-p0)/p0*100
                if inv: ret = -ret          # futures su XXX/USD
                blok = scoreCOT(f["delta"]) + scoreTQ(f["tq"], f["delta"]) \
                       + scoreWeekly(f["dL"], f["dS"], f["delta"])
                rec = {"date": f["date"], "delta": f["delta"], "blok": blok,
                       "pct": f["pct"], "ret": ret}
                A = agg[model]
                if abs(f["delta"]) >= SIGNAL_MIN: A["delta"].append(rec)
                if abs(blok) >= 10:              A["blok"].append(rec)
                if f["pct"] is not None:
                    if f["pct"] >= 95: A["ext_hi"].append(rec)
                    if f["pct"] <= 5:  A["ext_lo"].append(rec)
        print(f"── {ccy}: obradjeno")

    print("\n" + "=" * 78)
    print("TEST A — STVARNI CME COT BLOK  (cotMom + tq + weekly)  vs  sirovi delta6w")
    print("=" * 78)
    print(f"  {'':<24}{'hit':>9}{'%':>8}{'z':>8}{'p':>9}")
    for m in MODELS:
        for key, lab in (("delta", "delta6w (sirovi)"), ("blok", "CME COT BLOK")):
            rows = agg[m][key]
            h = sum(1 for r in rows if (r[key if key == "blok" else "delta"] > 0) == (r["ret"] > 0))
            print(hitline(f"{m} · {lab}", h, len(rows)))
        print()

    print("=" * 78)
    print("TEST B — WALK-FORWARD  (starija polovina vs novija polovina)")
    print("=" * 78)
    for m in MODELS:
        rows = sorted(agg[m]["delta"], key=lambda r: r["date"])
        if len(rows) < 40:
            print(f"  {m}: premalo tacaka"); continue
        mid = len(rows)//2
        halves = [("starija " + rows[0]["date"][:7] + "→" + rows[mid-1]["date"][:7], rows[:mid]),
                  ("novija  " + rows[mid]["date"][:7] + "→" + rows[-1]["date"][:7], rows[mid:])]
        print(f"  ── {m} ──")
        for lab, part in halves:
            h = sum(1 for r in part if (r["delta"] > 0) == (r["ret"] > 0))
            print(hitline("   " + lab, h, len(part)))
        print()

    print("=" * 78)
    print("TEST C — PERCENTIL / EKSTREMI  (rolling 3g, bez gledanja unapred)")
    print("=" * 78)
    print("  Hipoteza: ekstrem je KONTRARIAN — prenatrpano long -> cena pada.")
    print("  'hit' ovde = da li se cena okrenula PROTIV ekstrema.\n")
    for m in MODELS:
        hi, lo = agg[m]["ext_hi"], agg[m]["ext_lo"]
        h_hi = sum(1 for r in hi if r["ret"] < 0)      # prenatrpano long -> pad = pogodak
        h_lo = sum(1 for r in lo if r["ret"] > 0)      # prenatrpano short -> rast = pogodak
        avg_hi = sum(r["ret"] for r in hi)/len(hi) if hi else 0
        avg_lo = sum(r["ret"] for r in lo) /len(lo) if lo else 0
        print(f"  ── {m} ──")
        print(hitline("   percentil >95 (long)", h_hi, len(hi), f"  pros.prinos {avg_hi:+.2f}%"))
        print(hitline("   percentil <5  (short)", h_lo, len(lo), f"  pros.prinos {avg_lo:+.2f}%"))
        both_h, both_n = h_hi + h_lo, len(hi) + len(lo)
        print(hitline("   OBA ekstrema", both_h, both_n))
        print()

    print("""
KAKO CITATI
  σ = koliko standardnih devijacija od nasumicnog (50%). |σ|>2 = znacajno.
  ◄ EDGE  = model ima informaciju u tom smeru
  ◄ ANTI  = model je znacajno POGRESAN (okrenut bi radio)
  bez oznake = sum, nema signala

  TEST A: da li ceo CME blok radi bolje od sirove delte?
  TEST B: ako je efekat u OBE polovine -> prava osobina, ne rezim.
          Ako je samo u jednoj -> artefakt, ne diramo nista.
  TEST C: ako ekstremi imaju edge a smer nema -> COT treba koristiti
          kao kontrarian na ekstremima, ne kao trend-follow na smeru.
""")


if __name__ == "__main__":
    _t = _Tee(_OUT); sys.stdout = _t
    try:
        main()
    except Exception:
        import traceback; print("\nGRESKA:"); traceback.print_exc(file=_t)
    finally:
        print(f"\n[ispis sacuvan u: {_OUT}]")
        sys.stdout = sys.__stdout__; _t.flush()
        try: input("\nPritisni Enter za zatvaranje...")
        except Exception: pass
