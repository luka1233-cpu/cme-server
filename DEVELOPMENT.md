# CME Economic Heatmap — DEVELOPMENT.md

Dnevnik razvoja i odluka. Cilj: svaka odluka ima dokumentovan razlog,
bez potrebe za kopanjem po chat istoriji.

---

## V1 — ZAKLJUČAN 3. jula 2026.

**Kriterijum zaključavanja:** audit svih 8 valuta vs A1 EdgeFinder sa
0 × BUG + 0 × UNKNOWN. Ispunjen 3. jula 2026.

**Rezultat audita (61 poređenje):** 45 MATCH (74%) · 12 DATA_SOURCE ·
4 METHODOLOGY · 0 BUG · 0 UNKNOWN

Sve izmene posle ovog datuma idu u V1.1 ili V2 — V1 logika i pragovi se ne diraju.

---

## 1. Arhitektura

```
run_cme.bat
    ├── update_news.py                     → news.json (News Impulse)
    ├── engine/run_engine.py
    │       ├── collectors/macro_collector.py   (FMP → sirovi podaci)
    │       ├── collectors/indicator_config.py  (SVA konfiguracija na jednom mestu)
    │       └── engines/macro_engine.py         (score → heatmap.json)
    │               └── engines/signal_functions.py (per-indicator signali)
    └── python -m http.server 8000 → cme.html + mme.html
```

**Principi:**
- Jedan izvor podataka: FMP `stable/economic-calendar` (90 dana unazad)
- Konzistentan algoritam za svih 8 valuta — **nema per-currency hakova**
- Sva konfiguracija (pragovi, težine, preferencije, MODE) u `indicator_config.py`
- Signal funkcije vraćaju -1/0/+1; arhitektura spremna za V2 float score bez prepravke engine-a

---

## 2. Model (kategorije i težine)

| Kategorija | Težina | Indikatori (unutar-kategorijske težine) |
|---|---|---|
| GDP | 20% | GDP (1.0) |
| CPI / Inflacija | 15% | CPI 1.0, HICP 1.0, Core CPI 0.8, PCE 0.7 |
| Employment | 15% | NFP 1.0, Employment 0.9, Unemployment 0.6, ADP 0.3, Jobless Claims 0.3, JOLTS 0.3 |
| PMI Manufacturing | 10% | PMI_MFG (1.0) |
| PMI Services | 10% | PMI_SVC 1.0, PMI_COMP 0.6 |
| Retail Sales | 10% | RETAIL_SALES (1.0) |
| Rates / Wages | 10% | Interest Rate 1.0, Wages 0.6 |
| PPI | 5% | PPI (1.0) |
| Confidence / Other | 5% | Confidence 1.0, Industrial Prod 0.6, Trade Balance 0.05, Current Account 0.05 |

**Zašto NFP dominira Employment kategorijom (1.0 vs ADP 0.3):** tržište tretira
NFP kao primarni signal; bearish NFP mora da prepiše bullish ADP. Verifikovano
testom oba scenarija — NFP nosi ~77% težine kad su oba prisutna.

**Zašto Trade Balance / Current Account imaju 0.05:** A1 ih ne koristi za FX
Impact; naša analiza pokazala da vuku USD nadole bez trading vrednosti.
Nisu izbačeni (nose malo informacije), samo marginalizovani.

**Nedostajuće kategorije** → težina se proporcionalno preraspodeljuje na dostupne.

**Heatmap % = (weighted_signal + 1) / 2 × 100**, gde weighted_signal ∈ [-1, +1].

---

## 3. MODE sistem i kalibracija neutral težine

Neutralne kategorije ulaze sa smanjenom efektivnom težinom:

```python
MODE = "CALIBRATED"      # neutral_weight = 0.3
# "A1"           = 0.0   (neutrali ignorisani, bullish/(bullish+bearish) stil)
# "CONSERVATIVE" = 1.0   (puna težina, razblažuje ka 50%)
```

**Zašto 0.3, a ne 0.5 ili 0.0:** sweep test (jul 2026) na USD/GBP/JPY snapshot-u:

| Faktor | Prosečna greška vs A1 |
|---|---|
| 0.0 (A1 stil) | 6.00pp — JPY prebacuje na 93%! |
| **0.3** | **3.33pp — optimum** |
| 0.5 (prvobitni "logičan" izbor) | 5.33pp |
| 1.0 (staro) | 8.33pp |

Pouka: ni čisti A1 stil (0.0) nije dobar — A1 interno ipak ne ignoriše
neutrale skroz. Kalibracija > intuicija.

**Ograničenje:** kalibrisano na 1 snapshot / 3 valute. Plan: subotom se
akumuliraju A1 screenshotovi → re-sweep posle 8-10 nedelja na pravoj istoriji.

---

## 4. Pragovi (THRESHOLDS u indicator_config.py)

Relativni (% od forecasta): NFP/Employment/ADP 10%, **Jobless Claims 3%**,
**JOLTS 3%**. Apsolutni: GDP 0.2pp, CPI/Core/HICP/PCE 0.1pp, PPI 0.2pp,
PMI 0.3, Retail 0.2pp, Wages 0.1pp, Interest Rate 0.01pp, Unemployment 0.1pp,
Confidence 0.5, Trade/CA 0.5.

**Istorija kalibracije:**
- `JOBLESS_CLAIMS: 0.05 → 0.03` (jul 2026) — istorijski test na 90d podataka
  (`threshold_test.py`): 5/5 promenjenih signala bilo ispravno, 0 lažnih.
- `JOLTS: 0.05 → 0.03` (jul 2026) — isti test: 1/1 ispravno.
- Princip: **test → dokaz → izmena**, nikad kalibracija napamet na jednom primeru.

---

## 5. Signal logika — ključne odluke

- **Surprise prvo:** gde postoje Actual/Forecast/Previous, signal = surprise
  (Actual vs Forecast; fallback Previous). Fiksni pragovi samo gde imaju smisla.
- **PMI (posebno pravilo):** značajan surprise (≥0.3) pobedjuje; inače apsolutni
  nivo (>51 bull, <49 bear, između neutral). Razlog: 50 je fundamentalna granica
  ekspanzija/kontrakcija.
- **Interest Rate:** Actual vs **Previous** (hike/cut/hold) — forecast kod odluka
  centralnih banaka često već uračunava hike pa je surprise 0. Potvrđeno na
  EUR (2.4 vs prev 2.15) i JPY (1.0 vs prev 0.75) — oba hike = bullish, A1 isto.
- **Inverted indikatori:** Unemployment, Jobless Claims (manji broj = bullish).
- **Granična semantika (bugfix, v. sekciju 7):** razlika TAČNO jednaka pragu
  = signal, ne neutral. Diff se zaokružuje na 4 decimale pre poređenja.

---

## 6. Collector — izbor eventa

FMP vraća 10+ varijanti istog indikatora. Rešenje: **per-currency preferred
liste** u `indicator_config.py` (`GDP_PREFERRED`, `CPI_PREFERRED`...) +
`preferred_score()` — konfiguracija koja kaže koji event tržište primarno
čita za svaku valutu (npr. GBP GDP **MoM**, CAD GDP **MoM**, ostali QoQ;
USD PMI = **ISM**, ostali S&P Global).

**Univerzalni exclude (za sve valute):** GDPNow, GDP Price Index/deflator,
GDP Sales, **GDP Capital Expenditure/capex** (JPY bug — hvatao capex umesto
GDP Growth), U-6 Unemployment, Interest Rate Projections (Fed dot plot),
ISM sub-indeksi (New Orders...), Continuing Claims, JOLTs Quits,
Retail Ex Gas/Autos/Control Group.

Kad više eventa ima isti preferred score → uzima se noviji datum.

---

## 7. Bugfix-evi (hronološki)

1. **FMP endpoint 403** — `api/v3/economic_calendar` je deprecated;
   prelazak na `stable/economic-calendar`. Polje forecasta = `estimate`.
2. **PMI surprise ignorisan** — ISM 53.3 vs 54.0 davao bullish (jer >50);
   fix: surprise ≥0.3 ima prioritet nad apsolutnim nivoom.
3. **Pogrešni GDP eventi** — GDPNow, Price Index, Sales, Capital Expenditure
   hvatani umesto GDP Growth; rešeno exclude listama + preferred prioritetima.
4. **Pogrešni employment eventi** — U-6 umesto U-3 Unemployment, Continuing
   umesto Initial Claims, JOLTs Quits umesto Openings; rešeno exclude listama.
5. **Retail Ex Gas/Autos** umesto headline Retail Sales; rešeno exclude listom.
6. **⭐ Granični floating-point bug (nađen u finalnom auditu):**
   GBP Unemployment 4.9 vs 5.0 → neutral, ali NZD 5.3 vs 5.4 → bullish —
   ista nominalna razlika -0.1pp, različit rezultat! Uzrok: `4.9-5.0 =
   -0.0999...` a `5.3-5.4 = -0.1000...53` u floating point-u, pa poređenje
   sa pragom 0.1 daje nasumičan ishod. **Fix:** `round(diff, 4)` + granica
   `abs(diff) < threshold → neutral` (tj. diff jednak pragu = signal).
   Poravnalo 5 signala sa A1 (USD/EUR/GBP Unemployment, CHF PPI, AUD GDP).
7. **GDP pod-komponente (nađeno 7. jul, prvi COT-svež run):** izveštaj od
   30. juna uveo nove GDP varijante koje su prolazile exclude liste — JPY
   hvatao "GDP Private Consumption QoQ", CAD "GDP Implicit Price QoQ"
   (deflator), ranije i "GDP External Demand QoQ". **Fix:** dodato
   `private consumption`, `implicit`, `external demand` u sve GDP exclude
   liste u macro_collector.py (univerzalno, sve valute). Dozvoljen bugfix
   (pogrešan collector izbor), ne dira V1 metodologiju.

---

## 8. Audit vs A1 EdgeFinder (3. jul 2026)

Alat: `heatmap_audit.py` (u CME folderu). Ponovno pokretanje:
`python heatmap_audit.py engine\output\macro_raw.json`
(A1_DATA unutra treba osvežiti sa novih screenshotova za novi audit).

### 8.1 DATA_SOURCE razlike (12) — prihvaćene, ne diraju se

FMP i A1 koriste različite serije/revizije/mesece. Odluka: engine ostaje
dosledan FMP-u, **bez per-currency hakova** da bi se imitirao A1.

| Valuta · Indikator | Razlika |
|---|---|
| EUR GDP | FMP final revizija (0.6) vs A1 preliminary (-0.2) |
| EUR Retail | Različit mesec/serija |
| EUR PPI | FMP MoM vs A1 YoY serija |
| USD Wages | Različite serije (FMP 1.2/0.4 vs A1 YoY 3.5) |
| USD PCE | FMP **MoM** (0.4) vs A1 **YoY** (3.4) |
| JPY CPI | FMP serija (1.9) vs A1 National CPI (1.5) |
| CHF GDP | FMP 0.4 vs A1 0.7 — revizija/serija |
| AUD CPI | FMP mesečni (3.6) vs A1 kvartalni YoY (4.0) |
| CAD Retail | Različit mesec |
| CAD PMI Mfg | FMP ima forecast (miss), A1 poredi vs previous (beat) |
| NZD Retail, NZD CPI | Različite serije (QoQ vs YoY) |
| CHF PMI Svc, NZD oba PMI-a | **FMP nema te serije** (BusinessNZ, procure.ch) |

### 8.2 METHODOLOGY razlike (4) — namerno zadržane, dokumentovane

| Slučaj | Naša logika | A1 |
|---|---|---|
| USD Jobless Claims -2.3% | Prag 3% (istorijski kalibrisan) → neutral | Svaki beat = signal |
| NZD GDP -0.1pp | GDP prag 0.2pp → neutral | Svaki surprise = signal |
| GBP PMI Svc 48.8 vs 48.7 | Beat +0.1 < 0.3 → apsolutni nivo <49 = **bearish** (kontrakcija) | Čist surprise = bullish |
| JPY PMI Mfg 54.8 vs 54.9 | Miss -0.1 < 0.3 → apsolutni nivo >51 = **bullish** (ekspanzija) | Čist surprise = bearish |

Filozofija: A1 flaguje svaki surprise bez praga; mi filtriramo šum pragovima
i kod PMI-a poštujemo fundamentalnu granicu 50. Naše pravilo smatramo
ispravnijim za male (šumne) razlike.

### 8.3 Filozofija poređenja sa A1

A1 je **referenca, ne meta**. Evaluacija po trading kriterijumima:
1. **Direction match** — isti Bull/Bear/Neutral smer po valuti (cilj ≥6/8)
2. **Top-3 / Bottom-3 match** — iste najjače i najslabije valute
3. **Rank correlation** — sličan redosled

Apsolutni procenat NIJE kriterijum. Ako A1 ima grešku (kao JPY GDP capex),
naš sistem ostaje ispravan umesto da imitira.

---

## 9. Poznata ograničenja V1

- Signali su trostepeni (-1/0/+1) — NFP +300K vredi isto kao +15K iznad
  praga. **V2 kandidat:** float score po jačini iznenađenja.
- Neutral weight kalibrisan na 1 snapshot / 3 valute — čeka višenedeljnu
  A1 istoriju za re-sweep.
- FMP Starter plan: ~90 dana istorije max (402 na 365d) — ograničava
  istorijske testove pragova.
- FMP kašnjenje unosa `actual` vrednosti 5-30 min posle objave — pokretanje
  odmah posle vesti može da je propusti (rešenje: pokreni ponovo kasnije).
- FMP nema: CHF Services PMI, NZ Manufacturing/Services PMI.

---

## 10. COT automatizacija (aktivan modul — jul 2026)

**Status:** kod radi na live CFTC podacima; brojevi se poklapaju sa
ručnim slikama (GBP 21.8% delta -18pp +32K shorts, JPY TQ 6/6, XAU 85.9%
— svi verifikovani). Modul praktično gotov, čeka samo prvu potvrdu na
svežem izveštaju.

### 10.1 Izvor i arhitektura

- **API:** CFTC Socrata `publicreporting.cftc.gov/resource/6dca-aqww.json`
  (Legacy Futures Only). **Bez API ključa** — javni dataset.
- **Fajl:** `engine/collectors/cot_collector.py` → `engine/output/cot.json`
- Nova faza `[3/3]` u `run_engine.py`, u try/except — greška na CFTC
  strani ne ruši News ni Heatmap.

### 10.2 Contract market kodovi (stabilni identifikatori)

| Valuta | Kod | Market |
|---|---|---|
| USD | 098662 | USD INDEX (ICE) — nema FX futures, koristi se indeks |
| EUR | 099741 | EURO FX (CME) |
| GBP | 096742 | BRITISH POUND (CME) |
| JPY | 097741 | JAPANESE YEN (CME) |
| CHF | 092741 | SWISS FRANC (CME) |
| CAD | 090741 | CANADIAN DOLLAR (CME) |
| AUD | 232741 | AUSTRALIAN DOLLAR (CME) |
| NZD | 112741 | NZ DOLLAR (CME) |
| XAU | 088691 | GOLD (COMEX) |

### 10.3 Šta collector računa

Za svaku valutu povlači 8 nedeljnih izveštaja (`$order DESC $limit 8`,
Non-Commercial Long/Short) i računa polja koja CME DATA blok koristi:
`longPct`, `longPct6wAgo`, `deltaPct6w`, `dLong`, `dShort`, `tqConsistent`
(broj od 6 nedeljnih koraka u smeru ukupnog 6-nedeljnog trenda).

### 10.4 Integracija u cme.html

`loadCotJson()` prepisuje **samo COT polja** u `DATA.currencies`.
Retail Sentiment i `note_sr`/`note_en` ostaju iz ručnog DATA bloka.
Ako `cot.json` ne postoji → fallback na ručni blok (staro ponašanje).
Nepoznate valute u cot.json (koje CME ne prati) se preskaču.
Header indikator `📊 COT DD.MM (N)` = datum izveštaja + broj valuta.

### 10.5 Freshness zaštita (odluka jul 2026)

CFTC objavljuje petkom ~15:30 ET, ali Socrata baza kasni nekoliko sati
do dan-dva sa unosom. Zapis je uvek od **utorka** (COT reference date).

Dijagnostikovano na primeru: 4. jul collector vraćao 2026-06-23 iako je
petkov izveštaj (2026-06-30) objavljen. `cot_debug.py` potvrdio da
2026-06-30 **ne postoji u API-ju** (`Postoji 2026-06-30: False`) —
dakle Socrata još nije unela izveštaj, kod je ispravan.

Query proveren: `$limit 8` sa `$order DESC` uzima najnovijih 8 (ne skriva
najnoviji), nema `$offset`, contract filter tačan. Zaključak: kad se baza
ažurira, collector automatski pokupi najnoviji zapis bez izmene koda.

**Ugrađene zaštite:** konzola ispisuje starost izveštaja + upozorenje ako
je stariji od 10 dana; header `📊 COT` indikator pocrveni sa ⚠ i tooltip-om
kad je izveštaj stariji od 10 dana.

### 10.6 Subotnji workflow posle COT automatizacije

Pokreni `run_cme.bat` (News + Heatmap + COT automatski) + pošalji samo
**Retail Sentiment** sliku. Sve ostalo je automatsko.

---

## 11. Gold Macro Score V1 (dizajn — jul 2026)

Zlato nema "svoju ekonomiju" — pravi drajveri su US makro (preko realnih
prinosa i USD snage), institucionalno pozicioniranje i tehnika. A1 Asset
Scorecard sklapa Gold iz 4 skora (Technical, Sentiment+COT, Fundamentals,
Economic). CME Gold V1 replicira **dva čista motora**, ostalo ide u V2.

### 11.1 Filozofija i ključna inverzija

**Za zlato je logika OBRNUTA od valute:** jak USD makro = **bearish** za
zlato (jače kamate, jači dolar → zlato pada). Yields rising = hawkish =
bearish. Ovo je jedina inverzija u celom engine-u i mora biti eksplicitna
u kodu.

### 11.2 Engine 1 — Gold Macro

Ulazi (svi imaju čist izvor + jasna pravila + debug — Lukin filter):
- **USD Growth** (GDP) — koristi postojeći USD macro signal
- **USD Inflation** (CPI/PCE)
- **USD Labor** (NFP/Unemployment/Jobless Claims)
- **2Y Treasury Yield trend** — rising = hawkish = bearish gold.
  Izbor 2Y (ne 10Y): najosetljiviji na Fed očekivanja, isto što A1 koristi.

Svi USD signali se **invertuju** za Gold (bullish USD → bearish Gold).

### 11.3 Engine 2 — Gold COT (već automatski povlačimo XAU 088691)

- **Net Positioning** — Long% (85.9% = institucije dominantno long)
- **Latest Buys/Sells** — dLong/dShort nedeljna promena
- **Extremes** — Long% na istorijskom ekstremu = kontra signal

### 11.4 AI zaključak

Objašnjava slaganje ili konflikt između Macro i COT. Primer:
"USD macro bearish za zlato, Treasury prinosi rastu (dodatni bearish
pritisak), ali institucionalni COT ostaje snažno bullish. Dugoročno
pozicioniranje u konfliktu sa kratkoročnim makro protivvetrom."

### 11.5 Šta NAMERNO ostaje za Gold V2 (i zašto)

- **DXY** — ne zbog cirkularnosti, nego jer trenutno ne dodaje dovoljno
  nezavisne informacije u odnosu na cenu i USD Macro, a komplikuje model.
  Korisno TEK kad postoji infrastruktura za makro-vs-tržišna-reakcija
  konflikt (USD Macro bullish ali DXY pada = tržište ignoriše makro).
- **Real Yields** — nema čist surprise/trend format; treba pouzdana logika.
- **Fed expectations / FedWatch** — nije u FMP calendar formatu.
- **Technical** (SMA, trend) i **Retail Sentiment**.

Pravilo za ulazak u engine (isto kao Heatmap V1): jasan izvor podataka +
jasna pravila + mogućnost debugovanja. Bez ta tri — čeka V2.

---

## 12. Float Score — Engine V2 (jul 2026)

**Status:** IMPLEMENTIRANO. Signal skaliran po jačini iznenađenja umesto
diskretnog −1/0/+1. engineVersion → 3.0.0.

### 12.1 Problem koji rešava

V1 je svaki surprise preko praga tretirao kao pun ±1. Posledica: valuta
sa 7 tesnih signala u istom smeru (svaki jedva preko praga) dobijala je
ekstreman heatmap. Primer JPY (realni FMP podaci): GDP 0.5 vs 0.3, CPI
1.9 vs 1.8, PMI_SVC 52.2 vs 51.8 — svi jedva preko, V1 svaki +1.0, ukupno
90%. PMI_MFG 54.8 vs 54.9 (zapravo PROMAŠAJ) V1 davao +1.0 zbog >50 pravila.

### 12.2 Formula

```
diff = actual − ref  (ili rel = (actual−ref)/|ref| za rel indikatore)
ako |diff| < prag  → 0.0  (neutral, isto kao V1)
inače → sign × clamp(|diff| / (prag × SATURATION), 1/SAT .. 1.0)
```

Smer UVEK dolazi iz `get_signal()` (string) — čuva SVU V1 logiku (PMI
pravila, inverzije, INTEREST_RATE preko previous). Float samo skalira
veličinu. `get_signal_value()` je nova numerička funkcija; `get_signal()`
(string) ostaje za prikaz.

### 12.3 SATURATION = 3.0 (izbor na osnovu realnih podataka)

Testirano skriptom `float_score_test.py` (V1 vs V2×3/×5/×8 na živim FMP
podacima). Nalaz: prosečna razlika V1 vs V2 = 13.5pp (nije šum). JPY
najveći outlier (90%→~66%, 32pp). Per-indikator JPY pokazao:
- 3× jedini zadržava pun uticaj pravih jakih (RETAIL_SALES 5.3 vs 3.2 →
  +1.00, PPI 6.3 vs 5.5 → +1.00) dok tesne spušta na ~0.33
- 5×/8× guše i prave signale (RETAIL_SALES pada na 0.66/0.41)

### 12.4 Konfiguracija (bez magic numbers)

U `indicator_config.py`: `USE_FLOAT_SCORE = True` (False = vrati V1),
`FLOAT_SCORE_SATURATION = 3.0`. Kad dođe outcome tracking, menja se samo
SATURATION i meri uspešnost (3× vs 4× vs 5× → % tačnih) bez diranja
engine-a — optimizacija na osnovu rezultata, ne pretpostavki.

### 12.5 Verifikacija

Engine daje JPY 68% (V2×3), poklapa se sa test skriptom. Prekidač
V1/V2 potvrđen: GDP tesno → V1 +1.0, V2 +0.33; RETAIL_SALES jako →
oba +1.0. Isti pipeline (ind_weights, kategorije, normalizacija) — samo
signal_value sloj promenjen.

---

## 13. Retail Sentiment — UKLONJEN (jul 2026)

**Odluka:** Retail je izbačen iz engine-a u celosti. `engineVersion` → **3.1.0**
(uklanjanje faktora menja sve score-ove — stari snapshoti su 3.0.0).

### 13.1 Zašto uklonjen

Dva razloga, drugi je odlučujući:

1. **Najmanje impaktan faktor.** `scoreRetail()` je davao bonus **samo** kad je
   retail kontra smeru signala **i** ekstreman (≥65), maksimum ±10, a bez
   Heatmap-a se prepolovi. Bio je kodiran kao dopunski kontrarian filter, ne
   driver. Retail je ionako derivat svega ostalog — kasni za institucijama i za
   fundamentom, a kad protivreči COT-u, COT pobeđuje skoro uvek.

2. **Radio je na zamrznutim podacima.** `retailLong` u `DATA` bloku je bio ručna
   vrednost iz neke prošle subote — **isti fosil kao `note_sr`/`note_en`** (§14).
   Sve ostalo oko njega se ažuriralo automatski, retail nije. Faktor koji ulazi
   u score na osnovu starih brojeva je gori od nepostojećeg faktora.

Izbor je bio: automatizovati ga ili ukloniti. Automatizacija (§13.2) je odbijena
jer nije vredna truda za faktor sa ±10 dometa — pa uklonjen.

### 13.3 Šta je uklonjeno

`scoreRetail()`, `retail` iz `calcCcy` (`baseScore = cotMom+tq+weekly+hm`),
Retail red u kartici, `retailLong` iz `DATA` bloka, retail iz snapshot-a
(`retailScore`, `inputs.retail*`), iz AI konteksta, iz `buildNote()`,
iz pair modala i History detalja. `retail_collector.py` obrisan,
`run_engine.py` vraćen na `[1/4]..[4/4]`, Myfxbook kredencijali iz `run_cme.bat`.

**Pažnja:** `RETAIL_SALES` (ekonomski indikator u Heatmap-u) NIJE dirano —
to je druga stvar.

### 13.2 Istraživanje Myfxbook-a (arhivirano, ako se ikad vrati)

Retail pozicioniranje je **vlasnički podatak brokera** — nema javnog izvora kao
CFTC za COT. Myfxbook Community Outlook je jedini koji je prolazio filter:
- `GET /api/get-community-outlook.json?session=` — besplatno 100 zahteva/24h
- Login preko **email+password** (nema API ključ); sesija IP-bound, TTL mesec dana
- Daje **parove**, pa treba agregacija na valute (ista logika kao COT indeks):
  `long(USD) = Σ long gde je USD baza + Σ short gde je USD quote`
- Njihov headline `longPercentage` je računat po **volumenu**, ne po broju pozicija
  (provereno: 3888/6820 = 57% pozicija short, ali javljaju 55 = volumen)
- Plan je bio čuvati **obe** metrike: volumen (koliko je novca izloženo) i
  trgovce (psihologija mase). Njihova divergencija ("mnogo ljudi long, mali deo
  kapitala long") bi bila poseban signal.
- Brojevi se ne bi poklapali sa A1 (drugi pool trgovaca) — DATA_SOURCE razlika.

---

## 14. Auto-note na karticama (jul 2026)

**Problem:** `note_sr` / `note_en` u `DATA` bloku bili su ručno pisani još iz
vremena kad je CME bio potpuno ručan. Automatizacija je rasla *oko* tog bloka i
prepisivala sve ostalo u letu (COT preko `loadCotJson`, heatmap preko
`loadHeatmapJson`, XAU note preko `loadGoldJson`) — **jedino beleške niko nije
prepisivao.** Prikazivale su se na dnu svake kartice kao da su trenutna analiza,
a bile su zamrznute u vremenu.

Konkretno: GBP je pisao "+32K novih shorta u jednoj nedelji, institucije
ubrzavaju", dok je isti taj `dShort` na kartici bio **−7195** (shortovi se
zatvaraju). Tekst je tvrdio suprotno od podataka pored sebe. To je bilo jedino
mesto u CME-u koje je moglo aktivno da zavede — svuda drugde je broj svež ili
jasno označen kao fallback.

**Rešenje:** `buildNote(ccy, d, s)` sklapa zaključak iz istih podataka.
Deterministički, bez API troška — isti princip kao Gold narativ.

Ne ponavlja redove iznad (`cotDescription()` već opisuje šta institucije rade);
note je "pa šta onda":
1. **Naslov** — konflikt (nivo + pad confidence) ima prioritet; inače poravnanje
   COT/Weekly/Heatmap ("čist bullish signal") ili "faktori mešoviti".
2. **Kontekst** (najviše jedan) — COT ekstrem (≥80% ili ≤20% long) → 6-nedeljni
   trend (|Δ| ≥ 15pp, sa stvarnim brojevima) → veliki nedeljni tok (|neto| ≥ 20K).
3. **Dopuna** — retail kontra (kad `scoreRetail` da bonus), vest promenila bias.

XAU zadržava Gold narativ iz `gold.json` (čita se direktno iz `GOLD_DATA`).
`note_sr`/`note_en` obrisani iz `DATA` bloka — nema mrtvih polja.

---

## 15. Disaggregated COT + Percentil — i šta su testovi pokazali (jul 2026)

**Status:** podaci se povlače i prikazuju. **Score nepromenjen** — `COT_MODEL = "legacy"`.

### 15.1 Šta je dodato

`cot_collector.py` V2 povlači **tri modela** po valuti i piše ih u `cot.json`
pod `models`:
- **legacy** — Non-Commercial iz Legacy Futures Only (`6dca-aqww`) ← *score koristi ovo*
- **levFunds** — Leveraged Funds iz TFF Futures Only (`gpe5-46if`) — hedge fondovi, brzi novac
- **assetMgr** — Asset Managers iz TFF — penzioni/institucionalni, spori novac

Zašto: Legacy sabija AM i LF u **jedan broj** iako često stoje na **suprotnim
stranama**. Realni EUR podaci: Asset Mgr **+237K net LONG** dok su Leveraged
Funds **−36K net SHORT**.

Plus **percentil neto pozicije** (3g rolling, `HISTORY_WEEKS` 8→160) i
**LF/AM divergencija**. Oba **informativna** — prikazuju se, ne boduju.

XAU je **samo legacy** — zlato nije u TFF-u (trebao bi Disaggregated izveštaj,
gde je ekvivalent "Managed Money"; taj Futures-Only dataset ID nije verifikovan).

### 15.2 Testovi — zašto score NIJE promenjen

**`cot_model_test.py`** (160 ned., 7 valuta, isti signal `delta6w` za sva tri
modela, cene iz FMP, JPY/CHF/CAD invertovani jer su futures XXX/USD):

| model | hit@4w | z | zaključak |
|---|---|---|---|
| legacy | 43.8% | −3.07σ | anti-prediktivan |
| levFunds | 39.4% | −5.30σ | jako anti-prediktivan |
| assetMgr | 48.5% | −0.71σ | šum |

Nijedan nema edge. Leveraged Funds **najgori** — logično: hedge fondovi jure
momentum i budu pregaženi. Izgledalo je kao da COT u CME-u ima **pogrešan znak**.

**`cot_validation_test.py`** (320 ned. — tri provere pre bilo kakve izmene):

**A — stvarni CME COT blok** (`cotMom+tq+weekly`) vs sirovi `delta6w`:
blok je bio ~1pp bolji, ali i dalje anti (−2.55σ legacy). Napomena:
`scoreCOT(delta) = clamp(delta*2, ±40)` ima **isti znak** kao delta — testirati
samo njega bi dalo identične brojeve. Blok se razlikuje jer `scoreWeekly` može
da ide **protiv** delte.

**B — WALK-FORWARD — ovo je odlučilo:**

| model | 2020-07→2023-07 | 2023-07→2026-06 |
|---|---|---|
| legacy | 48.6% (−0.71σ) **šum** | 43.0% (−3.57σ) anti |
| levFunds | 48.8% (−0.65σ) **šum** | 40.1% (−5.22σ) anti |
| assetMgr | 47.0% (šum) | 48.5% (šum) |

Anti-prediktivnost postoji **samo u novijoj polovini**, u starijoj je **nema**.
To je **režimski artefakt, ne osobina.** Da smo okrenuli znak posle prvog testa,
ugradili bismo period 2023–2026 u engine kao da je zakon prirode.

**C — percentil/ekstremi** (rolling 3g, pun prozor, bez gledanja unapred):

| model | oba ekstrema (>95 / <5) | σ |
|---|---|---|
| legacy | 59.0% | 2.93 |
| levFunds | 58.2% | 2.52 |
| assetMgr | 58.3% | 2.70 |

**Sva tri nezavisno daju ~58–59% kontrarian edge na ekstremima.** Konzistentnost
preko tri modela nije tipična za šum — ovo je najzanimljiviji nalaz istraživanja.

### 15.3 Odluka (12. jul)

- **COT ostaje standardan** (kako ga profesionalci čitaju). Nema okretanja znaka.
- **Disaggregated** dostupan kao dodatna analiza, ne u score-u.
- **Percentil** informativno (`p97⚠` na ekstremu), **ne u score-u**.
- **LF/AM divergencija** prikazana (`⚔ brzi vs spori novac`), bez uticaja na score.

Percentil **nije prošao walk-forward** — nismo ga ni delili na polovine. To je
**isti prag koji je odbacio okretanje znaka**. Dosledno: prikaz, ne bodovanje,
dok ne prođe istu proveru.

Sve se **beleži u snapshot** (`inputs.cotPercentile3y`, `cotNetPosition`,
`cotModels`, `lfAmDivergence`) — pa kasniji walk-forward test percentila ima
podatke bez ponovnog povlačenja.

**Ako percentil jednom prođe split-sample na dužem periodu**, prebacivanje je
jedan red: `COT_MODEL` u configu + bodovanje ekstrema.

---

## 16. Sledeći moduli

Završeno: ✅Heatmap V1 → ✅COT → ✅Gold V1 → ✅History snapshots →
✅Float score (Engine V2, §12) → ❌Retail (uklonjen, §13) → ✅AI Chat →
✅Auto-note (§14) → ✅Disaggregated COT + Percentil (§15, informativno)

Odloženo:
- **Intermarket** — čeka pun izvor. FMP plan nema ne-US 2Y prinose (svih pet
  → 402 Premium), ni WTI ni bakar. Bez diferencijala prinosa modul nema
  najjaču komponentu. Vraćamo se kad budemo imali 2Y za sve zemlje + robe.
  (Radi: US 2Y, Brent BZUSD, zlato GCUSD, VIX, S&P.)
- **XAU Disaggregated** (Managed Money) — treba verifikovati Futures-Only
  dataset ID; ne pogađati.

Preostalo:
1. **Signal outcome tracking** — popunjava `outcome: null` u snapshot `pairs`
   bloku (bias tačan?, pomak cene, MFE/MAE). Tek ovo daje podatke za sve dalje
   odluke. **Sada je i najvredniji sledeći korak** — istraživanje iz §15 je
   pokazalo da bez merenja ishoda sve ostalo ostaje nagađanje.
2. **Walk-forward test percentila** na dužem periodu — jedini nalaz iz §15 sa
   naznakom edge-a (~58-59%, 2.5-2.9σ preko sva tri modela). Ako prođe
   split-sample, ulazi u score.
3. **Gold V2** — Real Yields, Fed expectations, Technical. (DXY odložen jer ne
   dodaje dovoljno nezavisne informacije uz USD Macro.)
4. **Neutral weight re-sweep** posle 8-10 nedelja akumulirane A1 istorije.
5. **Optimizacija na osnovu rezultata** (kad outcome tracking proradi):
   FLOAT_SCORE_SATURATION 3× vs 4× vs 5×, težine faktora, da li conflict
   penalty vredi — sve mereno, ne nagađano.

### Pravilo koje je izvučeno iz §15

Nijedna izmena osnovne logike engine-a bez **walk-forward** provere. Prvi test
je pokazao ubedljiv nalaz (COT anti-prediktivan, −5.3σ) koji se raspao čim je
podeljen na dve polovine — postojao je samo u novijem režimu. Jedan test na
jednom periodu nije dokaz, ma koliko sigma imao.
