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

# Picking a port. A previous run can still be holding 8934 - sometimes alive
# and usable, sometimes hung and answering nothing. Losing phone access
# entirely just because one port is taken is the worst outcome, so: reuse one
# of our own servers if it actually answers, otherwise move to the next free
# port rather than giving up.
LAST_PORT=$((PORT + 10))

for p in $(seq "$PORT" "$LAST_PORT"); do
  if curl -s -m 2 "http://127.0.0.1:$p/api/info" 2>/dev/null | grep -q stableHost; then
    echo "Сервер уже запущен на порту $p - открываю страницу."
    open "http://$IP:$p/"
    exit 0
  fi
done

CHOSEN=""
for p in $(seq "$PORT" "$LAST_PORT"); do
  if ! lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then CHOSEN="$p"; break; fi
done

if [ -z "$CHOSEN" ]; then
  echo "Все порты $PORT-$LAST_PORT заняты - открываю локально (без телефона)."
  open "$DIR/webapp/index.html"
  exit 0
fi

if [ "$CHOSEN" != "$PORT" ]; then
  echo "Порт $PORT занят другой программой - использую $CHOSEN."
fi
PORT="$CHOSEN"

python3 "$DIR/tools/lan_server.py" "$PORT" "$DIR/webapp" &
SERVER_PID=$!
sleep 1

if ! kill -0 $SERVER_PID 2>/dev/null; then
  echo "Не удалось поднять сервер на порту $PORT - открываю локально."
  open "$DIR/webapp/index.html"
  exit 0
fi

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null)"

echo ""
echo "=================================================================="
echo "  Открой на телефоне (в этой же Wi-Fi сети):"
echo ""
echo "  http://$IP:$PORT/"
if [ -n "$HOSTNAME_LOCAL" ]; then
  echo ""
  echo "  Постоянный адрес (НЕ меняется - его можно сохранить в закладки,"
  echo "  адрес выше зависит от роутера и со временем перестаёт работать):"
  echo "  http://$HOSTNAME_LOCAL.local:$PORT/"
fi
echo ""
echo "  На сайте есть кнопка «Показать QR» - можно отсканировать камерой."
echo "  Оба устройства смогут делиться страницей и файлом инструкции."
echo ""
echo "  Чтобы остановить сервер - закройте это окно или нажмите Ctrl+C."
echo "=================================================================="
echo ""

open "http://$IP:$PORT/"
wait $SERVER_PID
