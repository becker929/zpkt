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
2. **Plugins outside the DAW.** Steps 0 to 4 done 12 Sep
   (`results/offline_plugins_v1/`): parameter lists for LFOTool (70),
   COLDFIRE (~270), StandardCLIP (6); Decapitator exposes nothing; Anthony's
   LFOTool state read from the `.als` (9 dB volume pump, broadband); the
   pedalboard sweep is flat because pedalboard has no transport. **Done later the same day in DawDreamer**: transport at 160 BPM, state
   loaded by name, 13 depths, known answer matched within 0.5 dB; first
   offline knob-map row (`knob-map.md` row 3). Step 5 (round trip into Live)
   still waits for a swept state worth loading; `.adv`/`.als` is the route
   for a VST2 instance.
3. ~~Knob map, HW002 kick group~~ **Done 12 Sep**, ten rows, 130 steps,
   `results/knobmap_hw002_kickgroup_v1/`. Roar is bypassed in the set (five
   null rows) and the compressor is idle at Anthony's threshold (three flat
   rows); Threshold is the one live knob, 11 dB of crest span, not monotonic.
   Follow-up done 12 Sep (`..._v2_thr040/`): Attack, Release, Ratio at
   Threshold 0.4, labelled as an operating point. Ratio is the strong knob,
   6 dB of crest, monotonic above 0.33 and inverted in `knob-map.md`; Attack
   and Release move 1 to 2 dB and are not monotonic. The "what Roar would
   do" pack (Device On forced to 1; Drive, Tone Amt, Blend) is on the rig now.
3-old. Decided 12 Sep: Compressor
   Threshold, Attack, Release first, then Roar Drive, Tone Amt, Blend, then
   Ratio, Knee, Shaper 1 Amt, Shaper 1 Bias; whole range, 13 steps; an 8-bar
   loop of the real arrangement from the first kick bar, tapped at the
   group's output, so each row is about kick plus rumble as heard and the
   sidecar must list the bus members and their state. COLDFIRE exposes only
   on/off to the Live API: skipped on the rig, to be done offline in
   isolation as its own pack. Measures: crest and five band shares; decay40
   and sustain share if cheap.
3c. **Per-hit measures on loops.** `analysis.run hits` treats a file as one
   hit; on a 12 s loop it returns the file length. `lab/loop_hits.py`
   (12 Sep) segments at onsets first: 20 of 21 hits on a synthetic 160 BPM
   loop, the hit at t=0 missed. Second pass over the knob-map loops pending.
3b. **Runner headline on real multitracks.** `report_multitrack` still uses
   the corpus sidechain estimator, which saturates on solo stems (70 dB on
   HW002). The row is now labelled as a floor; the proper number needs a
   bypassed render and the `bypass` route.
4. **Calibrate the remaining measures** (requirement 2). Design agreed 12 Sep,
   the Mac is building it (`results/calibrate_measures_v1/`, one JSON per
   measure with the measure's exact definition recorded): grid lock on clicks
   and on 50 Hz bursts with tails at 140 and 160 BPM under 0 to 20 ms jitter;
   kick body at 40, 50, 60 Hz against analytic decay times; sustain share
   against the true energy ratio of a built burst plus plateau; band shares
   for BOTH sub definitions (20 to 60 in band_pump, 20 to 150 in
   signal_features) with tones at 50, 60, 150 and 300 Hz under 40 to 0 dB
   SNR; crest under clipping and under 0 to 2 s of trailing silence, the
   padding drift becoming the window rule. Tolerances: BPM 0.5% and phase
   10 ms; decay40 10%; sustain 0.02; shares 0.02 to 20 dB SNR; crest 0.5 dB.
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
