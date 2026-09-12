#!/bin/bash
# Job 2 step 4: sweep LFOTool's lfo_depth over its whole range, 13 steps, on the
# trimmed, bypassed rumble, starting from Anthony's actual LFOTool state so only
# depth changes. Then measure each step against the un-ducked input with the
# aligned bypass tool. Offline, faster than real time, no Live.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
PLUG="/Library/Audio/Plug-Ins/Components/LFOTool.component"
STATE=out/lfotool_state/lfotool_rumble.state
IN=stems/hw002_bypass/aligned__03__rumble__lfotool-off.wav
KICK=stems/hw002_bypass/aligned__02__kick.wav
OUT=out/plugin_sweeps
VALUES=$($PY -c "print(' '.join(f'{i/12:.6f}' for i in range(13)))")
echo "values: $VALUES"
$PY lab/plugin_sweep.py sweep --plugin "$PLUG" --load-state "$STATE" --param lfo_depth \
   --values $VALUES --input "$IN" --job rumble_lfotool_depth --out "$OUT" || exit 1
echo "--- sweep rendered; measuring each step ---"
mkdir -p "$OUT/bypass_json"
for w in "$OUT"/rumble_lfotool_depth__lfo_depth__*.wav; do
  b=$(basename "$w" .wav)
  $PY lab/duck_calibration.py bypass --kick "$KICK" --bass "$w" --bypass "$IN" \
     --out "$OUT/bypass_json/$b.json" >/dev/null 2>&1 && echo "measured $b" || echo "FAILED $b"
done
echo "SWEEP DONE"
