@echo off
setlocal enabledelayedexpansion
set DIR=%~dp0..\..
cd /d "%DIR%"

set PORT=8934
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
    echo Похоже, Python не найден или сервер не запустился. Полный вывод ipconfig:
    ipconfig
)
pause
