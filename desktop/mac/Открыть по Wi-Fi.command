#!/bin/bash
# Starts a local server for webapp/ reachable from other devices on the same
# Wi-Fi network (phone, tablet), and opens it in the default browser. Also
# exposes a tiny sync API (tools/lan_server.py) so a phone and a computer on
# the same page can share navigation and the loaded PDF.
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DIR" || { echo "Не найдена папка проекта"; read -p "Нажмите Enter..."; exit 1; }

PORT=8934
IP="$(ipconfig getifaddr en0 2>/dev/null)"
if [ -z "$IP" ]; then IP="$(ipconfig getifaddr en1 2>/dev/null)"; fi

if [ -z "$IP" ]; then
  echo "Не удалось определить IP-адрес компьютера в Wi-Fi сети."
  echo "Проверьте, что Wi-Fi включён, и посмотрите адрес вручную в Системных настройках -> Сеть."
  read -p "Нажмите Enter для выхода..."
  exit 1
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
echo "  На самом сайте будет кнопка «Показать QR» — можно просто"
echo "  отсканировать камерой телефона. Оба устройства также смогут"
echo "  делиться страницей и файлом инструкции между собой."
echo ""
echo "  Чтобы остановить сервер — закройте это окно или нажмите Ctrl+C."
echo "=================================================================="
echo ""

open "http://$IP:$PORT/"
wait $SERVER_PID
