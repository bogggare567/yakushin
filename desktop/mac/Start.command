#!/bin/bash
# One-click start. Tries to serve the site over your Wi-Fi (so a phone can
# also open it, with sync + QR); falls back to just opening it locally if
# no network is found. Either way, one double-click is all this takes.
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PORT=8934

IP="$(ipconfig getifaddr en0 2>/dev/null)"
if [ -z "$IP" ]; then IP="$(ipconfig getifaddr en1 2>/dev/null)"; fi

if [ -z "$IP" ]; then
  echo "Wi-Fi не найден - открываю локально (без доступа с телефона)."
  open "$DIR/webapp/index.html"
  exit 0
fi

python3 "$DIR/tools/lan_server.py" "$PORT" "$DIR/webapp" &
SERVER_PID=$!
sleep 1

echo ""
echo "=================================================================="
echo "  Открой на телефоне (в этой же Wi-Fi сети):"
echo ""
echo "  http://$IP:$PORT/"
echo ""
echo "  На сайте есть кнопка «Показать QR» - можно отсканировать камерой."
echo "  Оба устройства смогут делиться страницей и файлом инструкции."
echo ""
echo "  Чтобы остановить сервер - закройте это окно или нажмите Ctrl+C."
echo "=================================================================="
echo ""

open "http://$IP:$PORT/"
wait $SERVER_PID
