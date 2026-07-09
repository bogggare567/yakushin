@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0..\..\webapp" || (echo Не найдена папка webapp & pause & exit /b 1)

set PORT=8934
set IP=

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set IP=%%a
)
set IP=%IP: =%

if "%IP%"=="" (
    echo Не удалось определить IP-адрес автоматически.
    echo Посмотрите его сами командой ipconfig - строка "IPv4 Address" вашего Wi-Fi адаптера.
    ipconfig
    pause
    exit /b 1
)

echo.
echo ==================================================================
echo   Открой на телефоне (в этой же Wi-Fi сети):
echo.
echo   http://%IP%:%PORT%/
echo.
echo   На самом сайте есть кнопка "Показать QR" - можно просто
echo   отсканировать камерой телефона.
echo.
echo   Если не открывается - проверьте, что это действительно IP вашего
echo   Wi-Fi адаптера (см. полный вывод ipconfig выше), и что брандмауэр
echo   Windows не блокирует Python.
echo.
echo   Чтобы остановить сервер - закройте это окно.
echo ==================================================================
echo.

start "" "http://%IP%:%PORT%/"
python -m http.server %PORT% --bind 0.0.0.0
pause
