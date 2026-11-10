#!/bin/bash
# Download the DCLAP embedding model ears uses (AudioMuse-AI-DCLAP v1, AGPL-3.0, not ours to ship)
# into ~/.cache/zpkt/models/dclap, check it, and print where it is. ears finds it there by default.
#
#   ears/scripts/fetch_model.sh
#
# Only `ears analyze` embeddings, `ears compare` and the embedding part of `ears corpus` need it.
set -euo pipefail

BASE=https://github.com/NeptuneHub/AudioMuse-AI-DCLAP/releases/download/v1
DEST=${ZPKT_MODEL_CACHE:-$HOME/.cache/zpkt/models}/dclap
mkdir -p "$DEST"

fetch() {  # name sha256
  local out="$DEST/$1"
  if [ -f "$out" ] && [ "$(shasum -a 256 "$out" | cut -d' ' -f1)" = "$2" ]; then
    echo "ok (cached)  $1"; return
  fi
  curl -fL --progress-bar -o "$out.part" "$BASE/$1"
  if [ "$(shasum -a 256 "$out.part" | cut -d' ' -f1)" != "$2" ]; then
    rm -f "$out.part"; echo "checksum mismatch: $1" >&2; exit 1
  fi
  mv "$out.part" "$out"
  echo "fetched      $1"
}

fetch model_epoch_36.onnx      17860403f8fc90aff8ac0632a0741eb5e58d8c0b0ad2fce5ced967274b0ea971
fetch model_epoch_36.onnx.data 2a735b23c2aad7b12d9ffc85334cebcc659c07696d2ff60e2e378da28b6df657
echo "model: $DEST/model_epoch_36.onnx"
