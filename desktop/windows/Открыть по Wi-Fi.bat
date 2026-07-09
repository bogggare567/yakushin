@echo off
setlocal enabledelayedexpansion
set DIR=%~dp0..\..
cd /d "%DIR%" || (echo Не найдена папка проекта & pause & exit /b 1)

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
echo   отсканировать камерой телефона. Оба устройства также смогут
echo   делиться страницей и файлом инструкции между собой.
echo.
echo   Если не открывается - проверьте, что это действительно IP вашего
echo   Wi-Fi адаптера (см. полный вывод ipconfig выше), и что брандмауэр
echo   Windows не блокирует Python.
echo.
echo   Чтобы остановить сервер - закройте это окно.
echo ==================================================================
echo.

start "" "http://%IP%:%PORT%/"
python "%DIR%\tools\lan_server.py" %PORT% "%DIR%\webapp"
pause
