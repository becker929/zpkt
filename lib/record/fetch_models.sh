#!/bin/zsh
# Fetch the models ears needs from R2 into a local cache, verify them, and
# print the env var to use. Models are never committed: every clone and CI
# run would carry them.
#
#   lib/record/fetch_models.sh            # then: export EARS_DCLAP_MODEL=...
#
# Needs a wrangler login with access to the anthonybecker-audio bucket. The
# models/ prefix is not served by the site (its /audio route only reads audio/).
set -euo pipefail

BUCKET=${ZPKT_BUCKET:-anthonybecker-audio}
CACHE=${ZPKT_MODEL_CACHE:-$HOME/.cache/zpkt/models}
typeset -A SHA256=(
  dclap/model_epoch_36.onnx      17860403f8fc90aff8ac0632a0741eb5e58d8c0b0ad2fce5ced967274b0ea971
  dclap/model_epoch_36.onnx.data 2a735b23c2aad7b12d9ffc85334cebcc659c07696d2ff60e2e378da28b6df657
)

for key sum in ${(kv)SHA256}; do
  out=$CACHE/$key
  if [[ -f $out ]] && [[ $(shasum -a 256 $out | cut -d' ' -f1) == $sum ]]; then
    print "ok (cached)  $key"; continue
  fi
  mkdir -p ${out:h}
  npx -y wrangler@4 r2 object get "$BUCKET/models/$key" --file "$out" --remote >/dev/null
  [[ $(shasum -a 256 $out | cut -d' ' -f1) == $sum ]] || { print -u2 "checksum mismatch: $key"; rm -f $out; exit 1; }
  print "fetched      $key"
done
print "export EARS_DCLAP_MODEL=$CACHE/dclap/model_epoch_36.onnx"
