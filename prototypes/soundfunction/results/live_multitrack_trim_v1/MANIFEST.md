# live_multitrack_trim_v1 — the 18 prior stems, cut to their real length

Job: mailbox comment 5644205375. Trim every stem in `live_multitrack_bounce_v1`
to the source track's own content length, keep the originals, run the bench
sheet over the trimmed copies, report lengths and reports. No Live involved.

## What ran

Trim: `lab/trim_stems.py`, using `content_end()` from `lab/duck_calibration.py`
(last sample above -60 dBFS relative to peak, plus a 2 s hold). Originals
untouched under `sweeps/out/live_multitrack_bounce_v1/`. Trimmed copies and
sidecars under `local_src/stems/<song>/`, each sidecar extended with
`original_duration_s`, `content_duration_s` and `trim_method`.

Cross-check: for HW002 kick and rumble the Live Object Model says the last
arrangement clip ends at beat 704, which is 264.0 s at 160 BPM. The audio cut
landed at 267.0 s and 266.0 s, that is 264 s plus the 2 s hold. The two
methods agree.

Bench: `lab/runner.py --local local_src --out reports/`. Two reports,
`multitrack-hw002.json` and `multitrack-snts-style-track.json`.

## Lengths

See `lengths.md` for every stem. The shape of it:

- Across all 18 stems, 38% of the recorded audio was music. 62% was silence.
- HW002's active stems keep 37 to 45%. Three keep only 23 to 27%, because
  those tracks stop well before the end of the arrangement.
- Three SNTS stems (`22__pad-wind`, `23__pad-hollow`, `26__27-warn3`) cut to
  2.3 to 2.6 s. They are single hits in a 412 s file. `26__27-warn3` peaks at
  -0.4 dBFS in that one hit.

## What fought us

**The runner's role labels are swapped on HW002.** Its headline reads
"sidechain from 03__rumble.wav into 02__kick.wav", with the rumble as the
kick-like stem and the kick as the bass-like one. The role model calls the
kick's hits "hook" and the rumble's hits "rumble", then picks the kick-like
stem by a different rule. The 46.94 dB it reports is therefore kick ducked by
rumble, measured on solo stems, by the estimator that is already known to
saturate above about 12 dB. Treat the number as neither the right pair nor a
real depth. The per-stem table in the same report is fine.

**SNTS has no sidechain pair.** Its report says `None dB`: the bass-like pick
is a 2.3 s one-shot. Correct behaviour, noted so nobody reads it as a failure.

**Nothing else.** Trim and bench together took under two minutes. No audio
left the machine.
