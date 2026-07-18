"""
cme_server_cloud.py
Railway verzija CME servera.

Razlike od lokalnog cme_server.py:
  - Sluša na 0.0.0.0 (Railway zahtev)
  - Port iz environment variable PORT
  - Engine se pokreće pri startu + svakih 6h automatski
  - JSON output se čuva u /tmp/ (Railway ephemeral filesystem)
  - CORS headers za Flutter app
  - /api/cot, /api/heatmap, /api/gold, /api/news endpointovi
  - /api/run-engine za ručni trigger
"""

import os
import json
import threading
import time
import urllib.request
import urllib.error
import http.server
import socketserver
from pathlib import Path
from datetime import datetime, timezone

PORT = int(os.environ.get("PORT", 8000))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
AI_MODEL = "claude-sonnet-4-6"

# Na Railway koristimo /tmp za output
OUTPUT_DIR = Path("/tmp/cme_output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Dodaj engine u path
import sys
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "engine"))


def run_engine():
    """Pokreće CME engine i upisuje JSON-ove u /tmp/cme_output/"""
    print(f"[engine] Pokretanje engine-a u {datetime.now(timezone.utc).isoformat()}")
    try:
        # Postavi output dir na /tmp
        import engine.collectors.macro_collector as mc
        import engine.collectors.cot_collector as cc
        import engine.collectors.yield_collector as yc
        import engine.engines.macro_engine as me
        import engine.engines.gold_engine as ge

        # Override OUTPUT_DIR u svim modulima
        mc.OUTPUT_DIR = OUTPUT_DIR
        cc.OUTPUT_DIR = OUTPUT_DIR
        yc.OUTPUT_DIR = OUTPUT_DIR
        me.OUTPUT_DIR = OUTPUT_DIR
        ge.OUTPUT_DIR = OUTPUT_DIR

        # Faza 1: Macro
        macro_data = mc.collect()
        if not macro_data:
            print("[engine] Macro collector nije vratio podatke.")
            return False
        mc.save_raw(macro_data)

        # Faza 2: Macro Engine → heatmap.json
        macro_results = me.run(macro_data)

        # Faza 3: COT
        cot_data = {}
        try:
            cot_data = cc.collect() or {}
        except Exception as e:
            print(f"[engine] COT greška: {e}")

        # Faza 4: Gold
        try:
            usd_macro = macro_results.get("USD") if isinstance(macro_results, dict) else None
            if usd_macro:
                cot_xau = cot_data.get("currencies", {}).get("XAU") if cot_data else None
                yield_trend = None
                try:
                    yield_trend = yc.collect()
                except Exception as e:
                    print(f"[engine] Yield greška: {e}")
                ge.run(usd_macro, cot_xau, yield_trend)
        except Exception as e:
            print(f"[engine] Gold greška: {e}")

        print("[engine] Done.")
        return True
    except Exception as e:
        print(f"[engine] Kritična greška: {e}")
        import traceback
        traceback.print_exc()
        return False


def engine_scheduler():
    """Pokreće engine pri startu, pa svakih 6 sati."""
    # Kratka pauza da server startuje
    time.sleep(5)
    while True:
        run_engine()
        # Svakih 6 sati
        time.sleep(6 * 60 * 60)


class CMECloudHandler(http.server.BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        """CORS preflight za Flutter app."""
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            self._json(200, {"ok": True, "time": datetime.now(timezone.utc).isoformat()})
            return

        # API endpointovi — vraćaju JSON fajlove
        api_map = {
            "/api/cot":      OUTPUT_DIR / "cot.json",
            "/api/heatmap":  OUTPUT_DIR / "heatmap.json",
            "/api/gold":     OUTPUT_DIR / "gold.json",
            "/api/macro":    OUTPUT_DIR / "macro_raw.json",
            "/api/news":     Path(__file__).parent / "news.json",
        }

        if path in api_map:
            fpath = api_map[path]
            if fpath.exists():
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    self._json(200, data)
                except Exception as e:
                    self._json(500, {"error": str(e)})
            else:
                self._json(404, {"error": f"Fajl ne postoji još — engine nije pokrenuo ili je u toku.", "path": str(fpath)})
            return

        # Status endpoint — kad je engine poslednji put radio
        if path == "/api/status":
            status = {"time": datetime.now(timezone.utc).isoformat(), "files": {}}
            for name, fpath in [("cot", OUTPUT_DIR / "cot.json"),
                                  ("heatmap", OUTPUT_DIR / "heatmap.json"),
                                  ("gold", OUTPUT_DIR / "gold.json")]:
                if fpath.exists():
                    try:
                        d = json.loads(fpath.read_text())
                        status["files"][name] = d.get("generatedAt", "unknown")
                    except:
                        status["files"][name] = "error"
                else:
                    status["files"][name] = None
            self._json(200, status)
            return

        self._json(404, {"error": "Not found"})

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/run-engine":
            # Ručni trigger engine-a
            thread = threading.Thread(target=run_engine, daemon=True)
            thread.start()
            self._json(200, {"ok": True, "message": "Engine pokrenut u pozadini."})
            return

        if path == "/ai-chat":
            self._handle_ai_chat()
            return

        self._json(404, {"error": "Not found"})

    def _handle_ai_chat(self):
        if not ANTHROPIC_API_KEY:
            self._json(200, {"ok": False, "error": "ANTHROPIC_API_KEY nije postavljen."})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages") or []
            context = body.get("context") or {}
            lang = body.get("lang", "sr")
        except Exception as e:
            self._json(400, {"ok": False, "error": f"bad body: {e}"})
            return

        system = self._build_system_prompt(context, lang)
        payload = {
            "model": AI_MODEL,
            "max_tokens": 1200,
            "system": system,
            "messages": messages,
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text")
            self._json(200, {"ok": True, "reply": text})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
            self._json(200, {"ok": False, "error": f"API greška {e.code}: {detail}"})
        except Exception as e:
            self._json(200, {"ok": False, "error": str(e)})

    def _build_system_prompt(self, ctx, lang):
        lang_line = ("Odgovaraj na srpskom, sažeto i direktno."
                     if lang == "sr" else "Answer in English, concise and direct.")
        return f"""Ti si analitički asistent ugrađen u CME (Currency Momentum Engine).
Imaš pun pristup trenutnom stanju engine-a (dole).
{lang_line}

TRENUTNO STANJE CME-a (JSON):
{json.dumps(ctx, ensure_ascii=False, indent=1)}"""

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[http] {fmt % args}")


if __name__ == "__main__":
    if not FMP_API_KEY:
        print("[UPOZORENJE] FMP_API_KEY nije postavljen — engine neće raditi.")
    if not ANTHROPIC_API_KEY:
        print("[UPOZORENJE] ANTHROPIC_API_KEY nije postavljen — AI Chat neće raditi.")

    # Pokreni engine scheduler u pozadini
    scheduler = threading.Thread(target=engine_scheduler, daemon=True)
    scheduler.start()
    print(f"[server] Engine scheduler pokrenut — prvi run za ~5 sekundi.")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), CMECloudHandler) as httpd:
        print(f"[server] CME Cloud server na portu {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[server] Zaustavljen.")
