@echo off
REM ============================================================
REM CME Runner
REM 1) Povlaci High impact vesti sa FMP, racuna News Impulse
REM    (sa decay-om) i cuva u news.json.
REM 2) Pokrece lokalni HTTP server (Python http.server) u ovom
REM    folderu, da bi fetch('news.json') radio bez CORS problema.
REM 3) Otvara http://localhost:8000/cme.html u browseru.
REM
REM cme.html se NIKAD ne menja — samo cita JSON fajlove preko
REM lokalnog servera.
REM ============================================================

REM ============================================================
REM KLJUCEVI ZIVE U keys.bat — NE OVDE.
REM Razlog: run_cme.bat se povremeno menja i zamenjuje. Da su kljucevi
REM ovde, svaka nova verzija bi ih prebrisala (i jeste — 17. jul).
REM keys.bat se NIKAD ne isporucuje, pa ostaje netaknut zauvek.
REM Ako keys.bat ne postoji, pravi se automatski ispod.
REM ============================================================
if not exist "keys.bat" (
    echo.
    echo   Pravim keys.bat — upisi kljuceve u njega pa pokreni ponovo.
    echo.
    > keys.bat echo @echo off
    >>keys.bat echo REM ============================================
    >>keys.bat echo REM Kljucevi — ovaj fajl se NIKAD ne isporucuje.
    >>keys.bat echo REM Slobodno zameni run_cme.bat, ovo ostaje.
    >>keys.bat echo REM ============================================
    >>keys.bat echo.
    >>keys.bat echo REM FMP — obavezan (vesti, heatmap, prinosi^)
    >>keys.bat echo set FMP_API_KEY=UPISI_SVOJ_FMP_KLJUC_OVDE
    >>keys.bat echo.
    >>keys.bat echo REM Anthropic — samo za AI Chat tab (opciono^)
    >>keys.bat echo set ANTHROPIC_API_KEY=UPISI_SVOJ_ANTHROPIC_KLJUC_OVDE
    notepad keys.bat
    pause
    exit /b
)
call keys.bat

if "%FMP_API_KEY%"=="UPISI_SVOJ_FMP_KLJUC_OVDE" (
    echo.
    echo   [!] FMP kljuc nije upisan u keys.bat — otvaram ga.
    echo.
    notepad keys.bat
    pause
    exit /b
)

REM --- Putanja do news.json ---
set CME_JSON_PATH=news.json

REM --- Koliko dana unazad da povlaci vesti ---
set CME_DAYS_BACK=7

REM --- Port za lokalni server ---
set CME_PORT=8000

cd /d "%~dp0"

echo ============================================
echo   CME Runner
echo ============================================
echo.

echo [1/4] Povlacim vesti i racunam News Impulse...
python update_news.py
if %ERRORLEVEL% NEQ 0 (
    echo   Greska pri povlacenju vesti.
    pause & exit /b 1
)

echo.
echo [2/4] Povlacim makro podatke i racunam Economic Heatmap...
python engine\run_engine.py
if %ERRORLEVEL% NEQ 0 (
    echo   Greska pri racunanju Heatmap-a. Nastavljam sa starim heatmap.json ako postoji...
)

echo.
echo [3/4] Proveravam da li je port %CME_PORT% slobodan...
REM Ako vec postoji server na tom portu (npr. od ranije pokrenutog run_cme.bat),
REM ne pokrecemo drugi — samo otvaramo browser na postojeci.
netstat -ano | findstr ":%CME_PORT% " | findstr "LISTENING" >nul
if %ERRORLEVEL% EQU 0 (
    echo   Server na portu %CME_PORT% vec radi — koristim postojeci.
) else (
    echo   Pokrecem lokalni HTTP server na portu %CME_PORT%...
    start "CME Local Server" /min cmd /c "python cme_server.py"
    REM Daj serveru trenutak da se podigne
    timeout /t 2 /nobreak >nul
)

echo.
echo [4/4] Otvaram cme.html i mme.html...
start "" "http://localhost:%CME_PORT%/cme.html"
timeout /t 1 /nobreak >nul
start "" "http://localhost:%CME_PORT%/mme.html"

echo.
echo ============================================
echo   Gotovo. Server radi u pozadini (minimizovan
echo   prozor "CME Local Server"). Zatvori ga rucno
echo   kada zavrsis, ili ce se ugasiti kad ugasis PC.
echo ============================================
pause
