# How to

Runbooks. Paths assume the branch is cloned at `~/sandbox/sound-function` and
the site at `~/sandbox/anthonybecker.me`.

## Set up the lab

    git clone -b sound-function-research https://github.com/becker929/anthonybecker.me ~/sandbox/sound-function
    cd ~/sandbox/sound-function
    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
    python3 -m pytest analysis/test_features.py synth/test_engine.py tools/test_plainlint.py -q

Do not install demucs unless separating full mixes is the job.

## Publish to the site

    cd ~/sandbox/sound-function && python3 tools/sync_site_copy.py     # mirrors this repo into the site, minus audio/secrets/docs
    cd ~/sandbox/anthonybecker.me && npm test                           # must be 0 failures
    git add -A && git commit && git fetch origin main && git rebase origin/main && git push origin main

A push to `main` deploys via Cloudflare in about a minute. Verify with curl.
`tools/sync_site_copy.py` requires the site clone to be at the path it
expects; edit `SITE` at the top if yours differs.

## Write a note

Copy an existing `notes/<slug>/index.html`, keep the header structure
(kicker "Notes · N", title, lede, byline "Written by <model>, addressed to
Anthony, <month year>, Follows <previous>"), add an entry to
`notes/manifest.json`, lint, publish. Tables use `<div class="tablewrap"><table>`
and are exempt from the prose rules; glossaries use `<dl class="glossary">`.

## Lint prose

    python3 tools/plainlint.py <file.html|.md> --vocab tools/vocab_simple.txt --glossary tools/glossary.txt --names tools/names.txt

Research parts must pass (11 words a sentence, 6 a paragraph, no hard
words). Notes historically ran looser (longest sentence 26 to 55 words, 12 to
54 hard words). Add genuine technical terms to `tools/glossary.txt`; add
proper nouns to `tools/names.txt`; reword everything else.

## Regenerate the register table

    python3 research/test_hypotheses.py

Rewrites the results table at the bottom of `research/hypotheses.md` from
the corpus files. Hand-added evidence belongs in the H-body paragraphs, which
survive regeneration; table edits do not.

## Rebuild the listening test

    python3 listen/real_sweeps.py              # renders out/real_sweeps from real one-shots (needs library/real/wav)
    python3 listen/realism_check.py --dir out/real_sweeps --json out/listen_realism_real.json
    python3 listen/make_pairs_real.py --target 40   # writes pairs.json, credits.json, namespaced mp3s into the site

Bump `SET_ID` in `make_pairs_real.py` for a new stimulus set so answers stay
separable. Read answers at https://anthonybecker.me/api/listen/export.

## Measure a duck

    python3 lab/duck_calibration.py calibrate --kick K.wav                      # does the measure saturate on this material
    python3 lab/duck_calibration.py corpus    --kick K.wav --bass B.wav          # the corpus number on a real pair
    python3 lab/duck_calibration.py bypass    --kick K.wav --bass B.wav --bypass B_off.wav   # exact gain curve per band

Bypass aligns the takes and cuts windows from content length itself. Read
depths past ~13 dB from the corpus/calibrate modes as floors.

## Sweep a plugin outside the DAW

    python3 lab/plugin_sweep.py list  --plugin /Library/Audio/Plug-Ins/VST3/<name>.vst3
    python3 lab/plugin_sweep.py sweep --plugin <path> --param <name> --values 0 0.25 0.5 0.75 1 --input <wav> --job <job> --out out/plugin_sweeps
    python3 lab/plugin_sweep.py state --plugin <path> --load-state <bytes> --dump

Outputs follow `<job>__<param>__<value>.wav` with a `.params.json` sidecar and
a `.state` file. Built-in names (Compressor, Distortion, ...) work for
testing where no VSTs exist.

## Run the bench sheet on local audio

    python3 lab/runner.py --local <folder> --out reports/

`<folder>` holds `tracks/`, `refs/`, and `stems/<song>/*.wav`. One JSON
report per item. `lab/report_html.py` renders a sheet from the reports.

## Extract one-shot features

    python3 -m analysis.run hits <folder> -o hits.csv && python3 analysis/hits_extra.py hits.csv

Both steps, always.

## Fetch from Anthony's Drive

`lab/drive_fetch.py manifest.json dest/` mirrors a shared folder given a
manifest of `{id, title, mimeType, path}`; it handles the virus-scan confirm
page. The web session used the Drive connector to list files; on the Mac,
Drive for desktop is simpler.

## Reach Anthony

    python3 ops/notify.py fyi|ask|act "message" [--title T] [--link URL]

Topic in `ops/local.env`. `act` becomes an Apple Reminder once
`ops/mac/install.sh` has been run by Anthony in his own Terminal.

## Ask the web session for a review

Comment on https://github.com/becker929/anthonybecker.me/pull/25 with a first
line of `@research`. It is woken by the comment and also checks every three
hours. Reply comes back on the same PR.

## Live rig

Documented on the Mac in `~/.agents/skills/ableton-live-control/` and
`~/sandbox/autodaw/hands/sweeps/HANDOFF.md`. Specs for jobs live in
`research/specs/`. Crash rules are in `CLAUDE.md`.
