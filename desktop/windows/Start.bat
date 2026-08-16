@echo off
setlocal enabledelayedexpansion
set DIR=%~dp0..\..
cd /d "%DIR%"

set PORT=8934

REM Auto-update: silently pull the latest version if this is an unmodified,
REM fast-forwardable git checkout - never touches local edits.
where git >nul 2>nul
if %errorlevel%==0 (
    if exist "%DIR%\.git" (
        git diff --quiet 2>nul && git diff --cached --quiet 2>nul && git pull --ff-only --quiet >nul 2>nul
    )
)

REM Which of this machine's addresses can the phone actually reach? Taking the
REM last "IPv4" line out of ipconfig, which this script used to do, lands on
REM VirtualBox, WSL, Hyper-V or a VPN adapter as often as on Wi-Fi - and a QR
REM code carrying one of those scans perfectly and then hangs forever, which is
REM precisely what "не открывается на телефоне" looks like from the phone. Ask
REM the routing table instead, the same way the server does.
set IP=
for /f "delims=" %%a in ('python "%DIR%\tools\lan_server.py" --addresses 2^>NUL') do (
    if not defined IP set IP=%%a
)
if "%IP%"=="" (
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do set IP=%%a
    set IP=!IP: =!
)

if "%IP%"=="" (
    echo Wi-Fi не найден - открываю локально ^(без доступа с телефона^).
    start "" "%DIR%\webapp\index.html"
    pause
    exit /b 0
)

REM A previous run may still hold the port - alive and usable, or hung and
REM answering nothing. Reuse one of our own servers if it really answers,
REM otherwise move to the next free port instead of losing phone access.
set /a LAST_PORT=%PORT%+10
for /l %%p in (%PORT%,1,%LAST_PORT%) do (
    curl -s -m 2 "http://127.0.0.1:%%p/api/info" 2>NUL | findstr /c:"stableHost" >NUL
    if !errorlevel!==0 (
        echo Сервер уже запущен на порту %%p - открываю страницу.
        start "" "http://!IP!:%%p/"
        exit /b 0
    )
)

set CHOSEN=
for /l %%p in (%PORT%,1,%LAST_PORT%) do (
    if not defined CHOSEN (
        netstat -an | findstr /c:":%%p " | findstr /i "LISTENING" >NUL
        if !errorlevel! neq 0 set CHOSEN=%%p
    )
)
if not defined CHOSEN (
    echo Все порты %PORT%-%LAST_PORT% заняты - открываю локально ^(без телефона^).
    start "" "%DIR%\webapp\index.html"
    pause
    exit /b 0
)
if not "!CHOSEN!"=="%PORT%" echo Порт %PORT% занят другой программой - использую !CHOSEN!.
set PORT=!CHOSEN!

REM Windows blocks incoming connections to python.exe unless someone allowed it
REM in the popup at first launch, and a "Cancel" there is remembered forever as
REM a block rule - after which the phone can never connect and nothing on
REM screen says why. Opening the port outright needs administrator rights, so
REM this tries and stays quiet if it cannot; the page itself now tells the user
REM whether the phone got through, and what to do if it did not.
netsh advfirewall firewall show rule name="abcTrain LEGO" >NUL 2>NUL
if errorlevel 1 (
    netsh advfirewall firewall add rule name="abcTrain LEGO" dir=in action=allow ^
        protocol=TCP localport=%PORT% profile=private >NUL 2>NUL
    if errorlevel 1 (
        echo   [i] Не удалось открыть порт в брандмауэре ^(нужны права администратора^).
        echo       Если телефон не подключится - запустите этот файл правой кнопкой,
        echo       "Запуск от имени администратора", один раз.
        echo.
    )
)

echo.
echo ==================================================================
echo   Открой на телефоне (в этой же Wi-Fi сети):
echo.
echo   http://%IP%:%PORT%/
echo.
echo   На сайте есть кнопка "Показать QR" - можно отсканировать камерой.
echo   Оно само напишет, подключился телефон или нет.
echo.
echo   Чтобы остановить сервер - закройте это окно.
echo ==================================================================
echo.

start "" "http://%IP%:%PORT%/"
python "%DIR%\tools\lan_server.py" %PORT% "%DIR%\webapp"
if errorlevel 1 (
    echo.
    echo Похоже, Python не найден, порт %PORT% уже занят, или сервер не запустился.
    echo Открываю страницу локально вместо этого.
    start "" "%DIR%\webapp\index.html"
)
pause
