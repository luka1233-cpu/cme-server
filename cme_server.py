"""
cme_server.py
Lokalni HTTP server za CME — zamenjuje `python -m http.server`.

Radi sve što i http.server (služi cme.html, JSON fajlove...), plus:
  POST /save-snapshot  — prima kompletan snapshot iz cme.html (Final Bias
                         izračunat u JS-u) i upisuje ga u engine/output/history/.

Dedup po dataset-u: snapshot nosi "datasetId" (generatedAt iz heatmap.json).
Ako je taj dataset već arhiviran, server odgovara 200 "already-archived"
i NE piše duplikat. Tako refresh stranice ne pravi nove snapshote —
samo novi run_cme.bat (novi dataset) pravi novi snapshot.
"""

import os
import json
import urllib.request
import urllib.error
import http.server
import socketserver
from pathlib import Path
from datetime import datetime, timezone

PORT = 8000
# AI chat — kljuc ostaje na serveru (NIKAD u cme.html).
# Postavi u run_cme.bat:  set ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL = "claude-sonnet-4-6"
ROOT = Path(__file__).parent
HISTORY_DIR = ROOT / "engine" / "output" / "history"


class CMEHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path == "/ai-chat":
            self._handle_ai_chat()
            return
        if self.path != "/save-snapshot":
            self.send_error(404, "Unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            snap = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._json(400, {"ok": False, "error": f"bad body: {e}"})
            return

        date_str = (snap.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
        dataset_id = snap.get("datasetId")

        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        out = HISTORY_DIR / f"{date_str}.json"

        # Dedup: ako fajl za ovaj datum vec postoji sa istim datasetId, preskoci
        if out.exists() and dataset_id:
            try:
                existing = json.loads(out.read_text(encoding="utf-8"))
                if existing.get("datasetId") == dataset_id:
                    self._json(200, {"ok": True, "status": "already-archived",
                                     "date": date_str})
                    return
            except Exception:
                pass  # neispravan postojeci — prepisi

        # Upisi (novi dataset za taj datum, ili prvi put)
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(snap, f, indent=2, ensure_ascii=False)
            self._update_index()
            print(f"[snapshot] Archived {date_str} (dataset {dataset_id})")
            self._json(200, {"ok": True, "status": "saved", "date": date_str})
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})

    def _handle_ai_chat(self):
        """
        Proksira pitanje ka Anthropic API-ju sa CME kontekstom.
        Body: {"messages":[{role,content}...], "context":{...trenutno stanje CME...}}
        Kljuc NIKAD ne napusta server.
        """
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("UPISI"):
            self._json(200, {"ok": False,
                             "error": "ANTHROPIC_API_KEY nije postavljen. "
                                      "Dodaj u run_cme.bat:  set ANTHROPIC_API_KEY=sk-ant-..."})
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
            print(f"[ai] HTTP {e.code}: {detail}")
            self._json(200, {"ok": False, "error": f"API greska {e.code}: {detail}"})
        except Exception as e:
            print(f"[ai] Greska: {e}")
            self._json(200, {"ok": False, "error": str(e)})

    def _build_system_prompt(self, ctx, lang):
        """Sklapa system prompt sa kompletnim trenutnim CME stanjem."""
        lang_line = ("Odgovaraj na srpskom, sazeto i direktno."
                     if lang == "sr" else "Answer in English, concise and direct.")
        return f"""Ti si analiticki asistent ugradjen u CME (Currency Momentum Engine),
Lukin alat za Forex analizu. Imas pun pristup trenutnom stanju engine-a (dole).

KAKO CME RADI:
- Svaka valuta ima Final Score = COT + Trend Quality + Weekly + Heatmap + Retail + News + Penalty
- Par bias = spread (base finalScore - quote finalScore). Pozitivan = kupovina baze.
- Heatmap = ekonomski fundament (0-100%, >55 bullish, <45 bearish). Engine V3 koristi
  Float score: signal skaliran po jacini iznenadjenja (ne diskretno -1/0/+1).
- COT = institucionalno pozicioniranje (CFTC). Long% i delta 6 nedelja.
- KONFLIKT = COT smer protivreci Heatmap smeru za istu valutu. Ne menja SMER signala,
  nego smanjuje CONFIDENCE (blag -15%, jak -25%) i vadi par iz Top Setups.
- Alignment: Aligned = jedna valuta jaka + druga slaba (najcistiji setup);
  Opposed = obe iste strane; Neutral = bar jedna blizu nule.

PRAVILA ODGOVARANJA:
- Koristi ISKLJUCIVO podatke iz konteksta dole. Nikad ne izmisljaj brojeve.
- Ako podatak ne postoji u kontekstu, reci da ga nemas.
- Luka je iskusan trader (Austin Moneyball MBT Supply & Demand metodologija) — pisi
  strucno, bez osnovnih objasnjenja. Bez preporuka "kupi/prodaj" — daj analizu, on odlucuje.
- CME nema Technical/price komponentu. Ako pitanje trazi tehniku ili cenu, reci to jasno.
- {lang_line}

TRENUTNO STANJE CME-a (JSON):
{json.dumps(ctx, ensure_ascii=False, indent=1)}"""

    def _update_index(self):
        dates = sorted([p.stem for p in HISTORY_DIR.glob("*.json") if p.stem != "index"])
        index = {
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "dates":     dates,
            "count":     len(dates),
        }
        with open(HISTORY_DIR / "index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Tise logovanje — samo POST i greske
        if "POST" in (args[0] if args else "") or "404" in str(args):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), CMEHandler) as httpd:
        print(f"CME server na http://127.0.0.1:{PORT}/cme.html")
        print(f"Snapshot endpoint: POST /save-snapshot")
        if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("UPISI"):
            print(f"AI Chat: AKTIVAN ({AI_MODEL})")
        else:
            print("AI Chat: iskljucen — postavi ANTHROPIC_API_KEY u run_cme.bat")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer zaustavljen.")
