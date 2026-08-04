#!/usr/bin/env bash
# Upload a rendered WAV to Cloudflare R2 and update the /audio latest pointer.
# Usage: upload-audio.sh <path-to-wav>
set -euo pipefail

FILE="$1"
NAME=$(basename "$FILE")
BUCKET="anthonybecker-audio"
WORKER_DIR="$HOME/sandbox/anthonybecker.me"

# R2 upload via S3-compatible API (bucket-scoped credentials).
AWS_ACCESS_KEY_ID=$(security find-generic-password -a cloudflare -s CLOUDFLARE_ACCESS_KEY -w)
AWS_SECRET_ACCESS_KEY=$(security find-generic-password -a cloudflare -s CLOUDFLARE_SECRET_ACCESS_KEY -w)
S3_ENDPOINT=$(security find-generic-password -a cloudflare -s CLOUDFLARE_S3_API_ENDPOINT -w)
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

aws s3 cp "$FILE" "s3://$BUCKET/audio/$NAME" \
  --endpoint-url "$S3_ENDPOINT" \
  --content-type "audio/wav"

# KV update via wrangler (Workers Routes token scoped to anthonybecker.me).
CLOUDFLARE_API_TOKEN=$(security find-generic-password -a cloudflare -s CLOUDFLARE_API_TOKEN -w)
CLOUDFLARE_ACCOUNT_ID=$(security find-generic-password -a cloudflare -s CLOUDFLARE_ACCOUNT_ID -w)
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

cd "$WORKER_DIR"
wrangler kv key put "audio:latest" "$NAME" --binding AUDIO_KV --remote

echo "https://anthonybecker.me/audio"
