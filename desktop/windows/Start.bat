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

set IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set IP=%%a
)
set IP=%IP: =%

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

echo.
echo ==================================================================
echo   Открой на телефоне (в этой же Wi-Fi сети):
echo.
echo   http://%IP%:%PORT%/
echo.
echo   На сайте есть кнопка "Показать QR" - можно отсканировать камерой.
echo   Оба устройства смогут делиться страницей и файлом инструкции.
echo.
echo   Если не открывается - проверьте, что это действительно IP вашего
echo   Wi-Fi адаптера (см. полный вывод ipconfig ниже), и что брандмауэр
echo   Windows не блокирует Python.
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
