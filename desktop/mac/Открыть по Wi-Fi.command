#!/bin/bash
# Starts a local server for webapp/ reachable from other devices on the same
# Wi-Fi network (phone, tablet), and opens it in the default browser.
cd "$(dirname "$0")/../../webapp" || { echo "Не найдена папка webapp"; read -p "Нажмите Enter..."; exit 1; }

PORT=8934
IP="$(ipconfig getifaddr en0 2>/dev/null)"
if [ -z "$IP" ]; then IP="$(ipconfig getifaddr en1 2>/dev/null)"; fi

if [ -z "$IP" ]; then
  echo "Не удалось определить IP-адрес компьютера в Wi-Fi сети."
  echo "Проверьте, что Wi-Fi включён, и посмотрите адрес вручную в Системных настройках -> Сеть."
  read -p "Нажмите Enter для выхода..."
  exit 1
fi

python3 -m http.server "$PORT" --bind 0.0.0.0 &
SERVER_PID=$!
sleep 1

echo ""
echo "=================================================================="
echo "  Открой на телефоне (в этой же Wi-Fi сети):"
echo ""
echo "  http://$IP:$PORT/"
echo ""
echo "  На самом сайте будет кнопка «Показать QR» — можно просто"
echo "  отсканировать камерой телефона."
echo ""
echo "  Чтобы остановить сервер — закройте это окно или нажмите Ctrl+C."
echo "=================================================================="
echo ""

open "http://$IP:$PORT/"
wait $SERVER_PID
