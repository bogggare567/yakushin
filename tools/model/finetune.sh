#!/bin/bash
# Add new instruction booklets to the model WITHOUT risking what already works.
#
# The rule enforced here: a retrained model only replaces the shipped one if it
# is at least as good on every booklet the current model was already judged on,
# as well as on the new ones. If it is worse anywhere, nothing is touched and
# the old model keeps running. That is what stops "improving" the model from
# quietly making an existing set worse.
#
# Usage:  ./finetune.sh new1.pdf [new2.pdf ...]
set -euo pipefail
cd "$(dirname "$0")"

PY=./venv/bin/python
[ -x "$PY" ] || { echo "Нет окружения. Сначала: python3 -m venv venv && venv/bin/pip install torch pymupdf numpy scipy pillow"; exit 1; }
[ $# -ge 1 ] || { echo "Использование: ./finetune.sh новый.pdf [ещё.pdf ...]"; exit 1; }

# must match webapp/app.js — the checks below only mean something if they test
# the settings that actually ship
TOL=0.25
COLOR_VETO=45
ASPECT_VETO=0.15

CORPUS_FILE=corpus.txt
touch "$CORPUS_FILE"
for f in "$@"; do
  [ -f "$f" ] || { echo "нет файла: $f"; exit 1; }
  grep -qxF "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" "$CORPUS_FILE" \
    || echo "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" >> "$CORPUS_FILE"
done
mapfile -t ALL < "$CORPUS_FILE"
echo "Корпус (${#ALL[@]} файлов):"; printf '  %s\n' "${ALL[@]}"

echo
# extract_dataset.py also measures each icon's size in studs while it goes;
# train.py turns every pair of differing sizes into a certain negative. That is
# the one class the callout-box rule cannot produce, so it costs nothing here
# and is where the remaining errors live.
echo "=== 1/5  Извлекаю детали из всего корпуса ==="
$PY extract_dataset.py dataset_new.npz "${ALL[@]}"

echo
echo "=== 2/4  Дообучаю, продолжая с текущей модели ==="
# starting from the shipped weights rather than from scratch keeps what the
# model already knows and needs far fewer epochs
INIT=""
[ -f model.pt ] && INIT="--init model.pt"
$PY train.py dataset_new.npz --epochs 15 $INIT --out model_candidate.pt

echo
echo "=== 3/4  Сравниваю кандидата с текущей моделью на КАЖДОМ файле корпуса ==="
PASS=1
for f in "${ALL[@]}"; do
  echo "--- $(basename "$f")"
  if [ -f model.pt ]; then
    $PY qc.py model.pt "$f" --json-out /tmp/qc_old.json > /tmp/qc_old.log 2>&1 || true
    OLD_DUP=$($PY -c "import json;print(json.load(open('/tmp/qc_old.json'))['model']['duplicate_rate'])")
    OLD_MRG=$($PY -c "import json;print(json.load(open('/tmp/qc_old.json'))['model']['merge_rate'])")
  else
    OLD_DUP=1; OLD_MRG=1
  fi
  $PY qc.py model_candidate.pt "$f" --json-out /tmp/qc_new.json > /tmp/qc_new.log 2>&1 || true
  NEW_DUP=$($PY -c "import json;print(json.load(open('/tmp/qc_new.json'))['model']['duplicate_rate'])")
  NEW_MRG=$($PY -c "import json;print(json.load(open('/tmp/qc_new.json'))['model']['merge_rate'])")
  echo "    дубли  $($PY -c "print(f'{float('$OLD_DUP')*100:.2f}% -> {float('$NEW_DUP')*100:.2f}%')")"
  echo "    склейки $($PY -c "print(f'{float('$OLD_MRG')*100:.2f}% -> {float('$NEW_MRG')*100:.2f}%')")"
  # a small tolerance so pure noise doesn't block an otherwise good model
  WORSE=$($PY -c "print(1 if (float('$NEW_DUP') > float('$OLD_DUP')+0.005 or float('$NEW_MRG') > float('$OLD_MRG')+0.005) else 0)")
  [ "$WORSE" = "1" ] && { echo "    СТАЛО ХУЖЕ на этом файле"; PASS=0; }
done

echo
echo "=== 4/5  Проверяю ошибки, найденные вручную ==="
# The certain-pair QC above can only build pairs from parts sharing a callout
# box, and the mistakes that actually reach the user are the ones that class
# cannot contain: a 6x6 plate against an 8x8. Those were found by going through
# whole booklets by eye and written down; a new model has to keep them fixed or
# the improvement is only on paper.
for GT in groundtruth*.json; do
  [ -f "$GT" ] || continue
  GT_PDF=$($PY -c "import json;print(json.load(open('$GT'))['pdf'])")
  SRC=$(grep -F "$GT_PDF" "$CORPUS_FILE" | head -1)
  [ -n "$SRC" ] || { echo "  $GT: нет $GT_PDF в корпусе, пропускаю"; continue; }
  OLD_BAD=99
  [ -f model.pt ] && OLD_BAD=$($PY regression.py "$SRC" --truth "$GT" --model model.pt \
      --tol "$TOL" --color "$COLOR_VETO" --aspect "$ASPECT_VETO" --pages 900 2>/dev/null \
      | grep -oE 'осталось склеенными: [0-9]+' | grep -oE '[0-9]+$')
  NEW_BAD=$($PY regression.py "$SRC" --truth "$GT" --model model_candidate.pt \
      --tol "$TOL" --color "$COLOR_VETO" --aspect "$ASPECT_VETO" --pages 900 2>/dev/null \
      | grep -oE 'осталось склеенными: [0-9]+' | grep -oE '[0-9]+$')
  echo "  $GT: осталось склеенными $OLD_BAD -> $NEW_BAD"
  [ "${NEW_BAD:-99}" -gt "${OLD_BAD:-99}" ] && { echo "    СТАЛО ХУЖЕ на проверенных вручную"; PASS=0; }
done

echo
echo "=== 5/5  Решение ==="
if [ "$PASS" = "1" ]; then
  cp -f model.pt "model_prev_$(date +%Y%m%d_%H%M%S).pt" 2>/dev/null || true
  mv model_candidate.pt model.pt
  mv dataset_new.npz dataset.npz
  $PY export.py
  echo "ПРИНЯТО: новая модель установлена, webapp/vendor/partmodel.bin обновлён."
  echo "Предыдущая сохранена рядом как model_prev_*.pt на случай отката."
else
  rm -f model_candidate.pt dataset_new.npz
  echo "ОТКЛОНЕНО: кандидат где-то хуже текущей модели. Ничего не изменено."
  echo "Можно попробовать больше эпох или больше данных."
  exit 1
fi
