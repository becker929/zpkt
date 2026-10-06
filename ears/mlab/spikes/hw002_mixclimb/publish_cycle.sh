#!/bin/zsh
# One publish of /skrng batch 5: branch -> build + upload -> PR -> merge -> verify live -> clean up.
#   spikes/hw002_mixclimb/publish_cycle.sh TAG      (run inside ears/mlab)
# Needs the site checkout at ~/_agent_scratch/site, gh and wrangler logged in.
set -euo pipefail
TAG=${1:?tag}
SITE=~/_agent_scratch/site
MLAB=${0:A:h:h:h}
BR=skrng-batch-5-$TAG

cd $SITE
git switch -q main && git pull -q --ff-only
git switch -q -c $BR
cd $MLAB
uv run --with librosa --with pedalboard python spikes/hw002_mixclimb/publish.py --upload 2>&1 | grep -v -i warn | tail -20
cd $SITE
if git diff --quiet; then echo "no manifest change"; git switch -q main; git branch -q -D $BR; exit 0; fi
git add skrng/manifest.json skrng/batches.json
git commit -q -m "skrng: batch 5 mix alternates ($TAG)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -q -u origin $BR
URL=$(gh pr create --title "skrng: batch 5 mix alternates ($TAG)" --body "Batch 5: HW002 mix alternates, hill-climbed toward the four Bandcamp references (zpkt \`ears/mlab/spikes/hw002_mixclimb\`). Audio is in R2 already.

🤖 Generated with [Claude Code](https://claude.com/claude-code)")
echo "PR $URL"
if gh pr checks $URL 2>/dev/null | grep -q -E '\bfail\b'; then echo "CHECK FAILED, not merging"; exit 1; fi
gh pr merge $URL --squash
WANT=$(python3 -c "import json; print(' '.join(e['id'] for e in json.load(open('skrng/manifest.json')) if e.get('batch') == 5))")
for i in $(seq 1 30); do
  LIVE=$(curl -s "https://anthonybecker.me/skrng/manifest.json?r=$RANDOM" | python3 -c "import json,sys; print(' '.join(e['id'] for e in json.load(sys.stdin) if e.get('batch') == 5))" 2>/dev/null || true)
  [ "$LIVE" = "$WANT" ] && break
  sleep 20
done
[ "$LIVE" = "$WANT" ] || { echo "NOT LIVE after 10 min"; exit 1; }
BAD=$(python3 -c "
import json
for e in json.load(open('skrng/manifest.json')):
    if e.get('batch') == 5: print(e['file']); print(e['announce'])" | while read u; do
  c=$(curl -s -o /dev/null -w '%{http_code}' "https://anthonybecker.me$u"); [ "$c" = 200 ] || echo "$c $u"; done)
[ -z "$BAD" ] || { echo "AUDIO NOT 200: $BAD"; exit 1; }
git switch -q main && git pull -q --ff-only
git branch -q -D $BR 2>/dev/null || true
git push -q origin --delete $BR 2>/dev/null || true
git fetch -q --prune
echo "LIVE $(date +%T): $WANT"
