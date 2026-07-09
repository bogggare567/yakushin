#!/bin/bash
# Regenerates the desktop/ launchers' bundled copy of the site from webapp/.
# Run this after editing anything in webapp/ so the standalone Mac .app and
# Windows folder stay in sync with the source.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="webapp"
MAC_DEST="desktop/mac/Список деталей.app/Contents/Resources/webapp"
WIN_DEST="desktop/windows/webapp"

for dest in "$MAC_DEST" "$WIN_DEST"; do
  mkdir -p "$dest/vendor"
  cp "$SRC"/index.html "$SRC"/style.css "$SRC"/app.js "$SRC"/glyph-templates.js "$SRC"/version.json "$dest"/
  cp "$SRC"/vendor/qrcode.js "$dest"/vendor/
done

chmod +x "desktop/mac/Список деталей.app/Contents/MacOS/launcher"
echo "Synced webapp/ -> desktop/mac and desktop/windows"
