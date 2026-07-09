#!/bin/bash
# One-click start. Tries to serve the site over your Wi-Fi (so a phone can
# also open it, with sync + QR); falls back to just opening it locally if
# no network is found. Either way, one double-click is all this takes.
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PORT=8934

# Auto-update: silently pull the latest version before launching, but only
# if this is an unmodified git checkout (never overwrite local edits) and
# only fast-forward (never merge/rebase on someone's machine unattended).
if [ -d "$DIR/.git" ] && git -C "$DIR" diff --quiet 2>/dev/null && git -C "$DIR" diff --cached --quiet 2>/dev/null; then
  git -C "$DIR" pull --ff-only --quiet >/dev/null 2>&1
fi

IP="$(ipconfig getifaddr en0 2>/dev/null)"
if [ -z "$IP" ]; then IP="$(ipconfig getifaddr en1 2>/dev/null)"; fi

if [ -z "$IP" ]; then
  echo "Wi-Fi не найден - открываю локально (без доступа с телефона)."
  open "$DIR/webapp/index.html"
  exit 0
fi

# Reuse an already-running server on this port instead of failing with
# "address already in use" (e.g. a previous run still open in another tab).
if curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT/"; then
  echo "Сервер уже запущен на порту $PORT - открываю страницу."
  open "http://$IP:$PORT/"
  exit 0
fi

python3 "$DIR/tools/lan_server.py" "$PORT" "$DIR/webapp" &
SERVER_PID=$!
sleep 1

if ! kill -0 $SERVER_PID 2>/dev/null; then
  echo "Не удалось поднять сервер на порту $PORT (занят чем-то другим?) - открываю локально."
  open "$DIR/webapp/index.html"
  exit 0
fi

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
