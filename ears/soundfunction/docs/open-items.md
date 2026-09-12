# Open items, 12 September 2026

## Queued for the Mac agent (in order)

1. ~~Trim and measure `live_multitrack_bounce_v1`~~ **Done 12 Sep**, results
   under `results/live_multitrack_trim_v1/`: 38% of the recorded audio was
   music; HW002 kick and rumble cut to 267 and 266 s, agreeing with the Live
   API's beat 704. It exposed a bug in `lab/runner.py`: the kick/bass pair
   was chosen through the role model, which called the kick "hook", so the
   headline paired the stems backwards. Fixed the same day with a name-first,
   physics-second selector (`pick_pair`). The reports on the branch predate
   the fix; re-run the bench to refresh them.
2. **Plugins outside the DAW.** Check `~/sandbox/autodaw` for an existing
   pedalboard or DawDreamer demo first. Then: list LFOTool, Decapitator,
   COLDFIRE and StandardCLIP parameters; load Anthony's LFOTool state from the
   HW002 clone's `.als` buffer and dump it; sweep LFOTool depth on the
   bypassed rumble and calibrate the duck measure at known depths; round-trip
   one state back into Live via `.vstpreset` or `.adv`. Plan in
   `research/offline-plugins.md`. Posted to PR #25 on 12 Sep.
3. **Knob map, HW002 kick group** (Roar, Dist COLDFIRE, Compressor): native
   devices, so on the rig. One parameter at a time, whole range, 13 steps.
4. **Calibrate the remaining measures** (requirement 2 in the plan note):
   grid lock, kick body, sustain share, band shares under noise, crest under
   limiting. Build a known-answer case for each, record what comes back.
5. **Join critic to knob map for the kick** (requirement 5), then the
   kick-only loop (requirement 6), then the first overnight engineer
   (requirement 11, dated 16 Oct).

## Blocked on Anthony

- Run `ops/mac/install.sh` in his own Terminal (Reminders mirror, mailbox
  poll). The agent's permission layer refuses `launchctl`.
- Grant Accessibility to the Live agent's terminal only if a job genuinely
  needs the export dialog; tap bounces do not.
- Take the listening test once against the real stimuli (31 pairs, about 15
  minutes). All three existing answers are against the old synthetic set.
- Make one track to a target using the clipper table, bounce it, put it in
  Drive. Closes the loop by hand once.
- Optional: set `LAB_TOKEN` on the site so the runner can post reports.
- His choices between renders are the gating input for the taste model
  (requirement 7): roughly 200 needed; three a week gives 15 months, ten a
  day gives ten weeks.

## Open questions in the research

- **Pump depth correction.** The corpus measure saturates near 12 to 14 dB.
  The published corpus pump numbers are floors. A correction needs the
  measure fed known ducks on full mixes (not solo stems); the recovered
  LFOTool curve from the bypass run is the natural test signal.
- **H34 beyond one track.** Answered exactly on HW002's rumble (LFOTool,
  broadband). The corpus verdict stands. More real pairs would say whether
  the device choice is typical.
- **The role model** still runs the old four-source fit (synthetic to real
  0.346). A pack of one-shots rendered from Anthony's own racks
  (`research/live-oneshot-pack.md`) is the intended training data.
- **Separator floor.** Demucs on full mixes never shows a solo stem's true
  duck depth. Real multitracks are the ground truth; the trim job gives the
  first comparison.
- **Kick alignment in the bypass run** was unverified (kick and rumble do
  not correlate). It affects where the dip is reported, not how deep.

## Housekeeping

- `results/live_rumble_bypass_v1/` is on the branch; `live_multitrack_bounce_v1`
  audio is on the Mac only, untrimmed.
- The web session's container still holds 3.6 GB of Demucs excerpts and the
  corpus audio; regenerable, will be lost, needs nothing.
- The mailbox PR is a draft and must never be merged.
- `ops/local.env.example` carries `MAILBOX_PR=25`.
