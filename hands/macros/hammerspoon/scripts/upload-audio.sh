#!/usr/bin/env bash
# Upload a rendered WAV to Cloudflare R2 and update the /audio latest pointer.
# Usage: upload-audio.sh <path-to-wav>
set -euo pipefail

FILE="$1"
NAME=$(basename "$FILE")
BUCKET="anthonybecker-audio"
WORKER_DIR="$HOME/sandbox/anthonybecker.me"

CLOUDFLARE_API_TOKEN=$(security find-generic-password -a cloudflare -s CLOUDFLARE_API_TOKEN -w)
CLOUDFLARE_ACCOUNT_ID=$(security find-generic-password -a cloudflare -s CLOUDFLARE_ACCOUNT_ID -w)
export CLOUDFLARE_API_TOKEN
export CLOUDFLARE_ACCOUNT_ID

wrangler r2 object put "$BUCKET/audio/$NAME" \
  --file="$FILE" \
  --content-type="audio/wav" \
  --remote

cd "$WORKER_DIR"
wrangler kv key put "audio:latest" "$NAME" --binding AUDIO_KV --remote

echo "https://anthonybecker.me/audio"
