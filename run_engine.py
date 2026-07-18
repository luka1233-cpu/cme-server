"""
run_engine.py
Orchestrator — poziva sve collectors i engines redom.
Pokrece se iz run_cme.bat:
    python engine/run_engine.py
"""

import sys
import os
from pathlib import Path

# Dodaj engine folder u Python path
sys.path.insert(0, str(Path(__file__).parent))

from collectors.macro_collector import collect as collect_macro, save_raw
from collectors.cot_collector import collect as collect_cot
from collectors.yield_collector import collect as collect_yield
from engines.macro_engine import run as run_macro
from engines.gold_engine import run as run_gold
import json


def main():
    print("=" * 52)
    print("  CME Engine")
    print("=" * 52)

    fmp_key = os.environ.get("FMP_API_KEY", "")
    if not fmp_key:
        print("[error] FMP_API_KEY nije postavljen.")
        sys.exit(1)

    # ── Faza 1: Macro Collector ────────────────────────────
    print("\n[1/4] Macro Collector...")
    macro_data = collect_macro()
    if not macro_data:
        print("[error] Macro collector nije vratio podatke.")
        sys.exit(1)
    save_raw(macro_data)

    # ── Faza 2: Macro Engine → heatmap.json ───────────────
    print("\n[2/4] Macro Engine...")
    macro_results = run_macro(macro_data)

    # ── Faza 3: COT Collector → cot.json ───────────────────
    # Nezavisan od heatmap-a; greska ovde ne rusi ostatak.
    print("\n[3/4] COT Collector (CFTC)...")
    cot_data = {}
    try:
        cot_data = collect_cot() or {}
        if not cot_data:
            print("[warn] COT collector nije vratio podatke — "
                  "cme.html ce koristiti rucni DATA blok.")
    except Exception as e:
        print(f"[warn] COT collector greska: {e} — "
              f"cme.html ce koristiti rucni DATA blok.")

    # ── Faza 4: Gold Engine → gold.json ────────────────────
    # Cita USD iz macro_results + XAU iz cot_data + 2Y yield.
    # Nezavisan; greska ne rusi ostatak.
    print("\n[4/4] Gold Engine...")
    try:
        usd_macro = macro_results.get("USD") if isinstance(macro_results, dict) else None
        if usd_macro is None:
            print("[warn] Nema USD u macro rezultatima — preskacem Gold.")
        else:
            cot_xau = cot_data.get("XAU") if cot_data else None
            yield_trend = None
            try:
                yield_trend = collect_yield()
            except Exception as e:
                print(f"[warn] Yield collector greska: {e} — Gold bez yield faktora.")
            run_gold(usd_macro, cot_xau, yield_trend)
    except Exception as e:
        print(f"[warn] Gold engine greska: {e} — cme.html Gold koristi placeholder.")

    print("\n" + "=" * 52)
    print("  Done. heatmap.json + cot.json + gold.json su spremni.")
    print("=" * 52)


if __name__ == "__main__":
    main()
