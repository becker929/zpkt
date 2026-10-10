#!/bin/zsh
S=/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad
while read vid segs; do
  [ -z "$vid" ] && continue
  echo "=== $vid $segs $(date +%T)"
  (cd ~/Desktop/zpkt/hands && uv run python $S/arrange.py $vid "$segs" 2>&1 | tail -1) || { echo "ARRANGE FAIL $vid"; continue; }
  (cd ~/Desktop/zpkt/ears/mlab && uv run --with lameenc python $S/verify.py $vid "$segs" 2>&1 | tail -1)
done <<'L'
v02-short-24s 95-96,125-138
v03-short-30s 93-96,125-140
v04-ntn-48s-peak 121-152
v05-ntn-48s-break-drop 81-84,89-96,125-144
v06-ntn-60s 73-80,93-96,125-152
v07-snts-78s 65-80,81-88,93-96,125-148
v08-snts-90s 65-80,81-96,97-104,125-144
v09-ksms-shape-60s 81-96,125-148
v10-hedon-shape-60s 113-152
v00-demo-60s-fixed 73-80,81-84,93-96,125-148
L
echo DONE
