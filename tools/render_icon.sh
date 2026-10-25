#!/bin/sh
# Renders tools/app_icon.svg to the app's PNG icons with headless Chrome (tools/cdp.mjs), then sizes them.
#   sh tools/render_icon.sh
set -eu
cd "$(dirname "$0")/.."
out=$(mktemp -d)
printf '<html><body style="margin:0;background:#000"><img src="file://%s" width="1024" height="1024" style="display:block"></body></html>' \
  "$PWD/tools/app_icon.svg" > "$out/icon.html"
printf '[{"go": "file://%s"}, {"wait": 500}, {"shot": "icon"}]' "$out/icon.html" > "$out/steps.json"
node tools/cdp.mjs "$out" 1024x1024 "$out/steps.json" > /dev/null
for size in 512 192; do sips -z "$size" "$size" "$out/icon.png" --out "web/public/icons/icon-$size.png" > /dev/null; done
sips -z 180 180 "$out/icon.png" --out web/public/icons/apple-touch-icon.png > /dev/null
# Safari and others also ask for these at the root, whatever the page links to.
cp web/public/icons/apple-touch-icon.png web/public/apple-touch-icon.png
for size in 16 32 48; do sips -z "$size" "$size" "$out/icon.png" --out "$out/fav-$size.png" > /dev/null; done
python3 - "$out" web/public/favicon.ico <<'PY'
import struct, sys
from pathlib import Path
pngs = [(n, Path(sys.argv[1], f"fav-{n}.png").read_bytes()) for n in (16, 32, 48)]
head = struct.pack("<HHH", 0, 1, len(pngs))
offset, entries, data = 6 + 16 * len(pngs), b"", b""
for n, png in pngs:
    entries += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(png), offset + len(data))
    data += png
Path(sys.argv[2]).write_bytes(head + entries + data)
PY
rm -rf "$out"
echo "icons written to web/public/icons"
