# Running the lab on the Mac

Audio is large and it is Anthony's. So the measurements run where the audio
already is, and only numbers travel. This page is for the agent on the Mac.

## Set up once

```bash
git clone -b sound-function-research https://github.com/becker929/anthonybecker.me sound-function
cd sound-function
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 -m pytest analysis/test_features.py -q     # 6 tests, all should pass
```

Do not install demucs unless a job says to separate a full mix. Real
multitracks make it unnecessary, and it pulls in torch.

## Where the stems go

The `lab/runner.py --local` layout, so nothing needs renaming:

```
<local_src>/
  tracks/            whole mixes, one file each
  refs/              reference tracks
  stems/<song>/      one folder per set, one wav per track, with .params.json sidecars
```

The bounce job already writes `stems/<song>/` in this shape.

## The tools, and what each one returns

All of them write JSON. Send the JSON. Keep the audio.

| tool | what it answers | run |
|---|---|---|
| `lab/duck_calibration.py calibrate` | does the pump measure saturate, and at what depth | `--kick stems/hw002/02__kick.wav` |
| `lab/duck_calibration.py corpus` | the corpus band-pump numbers on a real pair | `--kick ... --bass ...` |
| `lab/duck_calibration.py bypass` | the ducking device's exact gain curve, per band | `--kick ... --bass ... --bypass <bass with device off>` |
| `lab/runner.py --local <local_src> --out reports/` | the bench sheet for every track and stem folder | writes one JSON report per item |
| `listen/realism_check.py --dir <folder of one-shots>` | how real a set of one-shots is against 318 measured real ones | writes `out/listen_realism.json` |
| `python3 -m analysis.run hits <folder> -o hits.csv` then `python3 analysis/hits_extra.py hits.csv` | per-sound features for a folder of ONE-SHOTS (both steps, always) | CSV |
| `lab/loop_hits.py <wav-or-folder> -o hits.csv` | per-hit features on LOOPS: segments at onsets, then the same measures per hit, plus a per-file summary of medians | CSV + .summary.csv |

## What to send back

- The JSON or CSV the tool wrote. Typically under 1 MB.
- A MANIFEST.md in the style of `live_multitrack_bounce_v1`: what ran, on
  what, what fought you.
- If the research agent asks to hear something, a clip of at most 30 s and
  20 MB, chosen to show the thing in question. Never a whole track by
  default. Never a folder.

## What not to do

- Do not upload stems, bounces or project files anywhere except Anthony's
  own Drive, and only when he asks.
- Do not run the listening test's stimulus builder here; it publishes.
- Do not edit the research pages; that side is the research agent's.

## When a tool is missing

Say so in the MANIFEST and stop. The research agent adds the tool to the
branch, and the next `git pull` brings it. That is the whole coordination
loop: specs and tools go out through the branch, numbers come back through
Drive.
