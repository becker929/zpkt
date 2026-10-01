#!/bin/zsh
# Publish a render to anthonybecker.me/skrng: upload the MP3 to R2 and print
# the manifest entry to add to skrng/manifest.json in the site repo.
#
#   lib/record/publish_render.sh render.mp3 2026-10-01-hw002-kick-loop "HW002 — kick loop, night 1"
#
# Publishing is public: only run it for renders Anthony has approved.
set -euo pipefail
[[ $# -eq 3 ]] || { print -u2 "usage: $0 <file.mp3> <id> <title>"; exit 2; }
FILE=$1 ID=$2 TITLE=$3
BUCKET=${ZPKT_BUCKET:-anthonybecker-audio}
[[ $FILE == *.mp3 ]] || { print -u2 "renders are published as MP3"; exit 2; }

npx -y wrangler@4.145.0 r2 object put "$BUCKET/audio/skrng/$ID.mp3" --file "$FILE" \
  --content-type audio/mpeg --remote >/dev/null
print -u2 "uploaded → https://anthonybecker.me/audio/skrng/$ID.mp3"

python3 - "$ID" "$TITLE" <<'PY'
import json, sys, datetime
id_, title = sys.argv[1:]
print(json.dumps({"id": id_, "title": title, "date": datetime.date.today().isoformat(),
                  "file": f"/audio/skrng/{id_}.mp3", "notes": ""}, indent=2, ensure_ascii=False))
PY
