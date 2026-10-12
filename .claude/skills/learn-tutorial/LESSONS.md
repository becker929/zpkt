# Lessons

These are the rules that runs taught this skill. Each rule carries:

- the run that taught it: the run number and the video id, as in `runs.jsonl`;
- the evidence;
- its status;
- where it is enforced: a script, a brief or the recovery guide.

**Status** is one of these:

- **seeded**: one run taught it;
- **confirmed (runs …)**: later runs met it again and it held;
- **revised (run N)**: a later run changed it.

**Pruning.** The retro keeps this file short. A rule a later run contradicts is revised or removed. A rule
that three later runs never met is moved into its script or brief and dropped from this file. Near-duplicates
are merged.

## Scrape

1. **Screencasts need a scene threshold of 0.03.** Add a frame every 2.5 s and drop near-duplicates by
   block difference.
   - *Evidence:* run 1 (HztFoqevNMU). The video's highest scene score was 0.156, so thresholds of 0.2–0.3
     found no cuts. This setting kept 27 of 79 candidate frames.
   - *Status:* seeded; built into `frames.py` defaults.
2. **Demo windows come from word durations, not gaps.** Parakeet stretches the last word before a playback
   over the music.
   - *Evidence:* run 1, where one word ran for 6 s over the first playback.
   - *Status:* seeded; built into `transcribe.py --demo`.
3. **Anchor loops by cross-correlation.** Fix beat 0 on a kick, then align every playback to it.
   - *Evidence:* run 1, where first-onset anchors were off by 0.14–0.2 beat. The skill's regression run
     also found a mouse click 57 ms before the loop.
   - *Status:* seeded; built into `anchor.py`.
4. **Label every strong onset class by band.** Do not stop at the classes you expected.
   - *Evidence:* run 1 missed a backbeat clap that its own high band showed as the strongest onsets. The
     verifier caught it.
   - *Status:* seeded; in the scrape brief.
5. **Generate prose claims from the measured tables.**
   - *Evidence:* run 1's target-sound text put every bass note on a loud perc hit, which its own perc map
     contradicted. The verifier caught it.
   - *Status:* seeded; `recipe_check.py --tables`.
6. **A pointer over a control is not a click.** Trace the control's state across frames.
   - *Evidence:* run 1 claimed a solo was clicked at 0:03, but it was lit from the first frame.
   - *Status:* seeded; in the readout checklist.
7. **Decide audio clips or MIDI early.** A tutorial in audio clips makes pitch and velocity inferred.
   Translate them into MIDI for a stock instrument.
   - *Evidence:* run 1.
   - *Status:* seeded; in the scrape brief.
8. **Read pitch only where nothing else is low,** or subtract a playback without the source. Mark impure
   readings approximate.
   - *Evidence:* run 1. Its E notes carried a 48 Hz component only 1 dB down.
   - *Status:* seeded; built into `pitch.py --minus` and the impure flag.
9. **Give the verifier a checklist of value categories and the tools.**
   - *Evidence:* run 1's scrape verifier took 14.6 min and checked 424 leaf values, five times the readout's
     own time.
   - *Status:* seeded; in the verifier brief. Watch `scrape_verifier_min` in runs.jsonl.

## Practice

10. **Calibrate every detector on synthetic events at known times before it decides anything.**
    - *Evidence:* run 1's Version B read spectral-flux frames 21 ms early (mlab `onset_envelope` frame index
      against onset time). That put two bass notes on the wrong hits, and the verifier caught it by
      re-implementing the method.
    - *Status:* seeded; built into `selftest.py`, which `preflight.py` runs.
11. **Write the method's rules before applying them.**
    - Log a decision for every grid position.
    - Mark any rule added after seeing a result.
    - Give the verifier the method text to re-implement.
    - *Evidence:* run 1, rule 4 and the timing bug above.
    - *Status:* seeded; in the practice brief.
12. **Screen candidate material with the method's own measure before building.**
    - *Evidence:* run 1's first stock loop had no off-beat main hits, so it was useless under a 4/4 kick.
    - *Status:* seeded; in the brief and in stock-substitutes.md.
13. **The recipe carries every level a render needs.** Fit unseen levels to the tutorial's audio.
    - *Evidence:* run 1 had faders on screen but no synth output or drum level. `balance.py` fitted them,
      each within about 3 dB.
    - *Status:* seeded; `levels` in the schema.
14. **Probe any device that might sound by itself** with an export that includes the lead-in.
    - *Evidence:* run 1's Vinyl Distortion crackled with no input, in every bar.
    - *Status:* seeded; `recovery.md#device-self-noise`.
15. **The absence test is template projection,** with a gain under 0.1 when absent and over 0.3 when
    present.
    - *Evidence:* run 1, where a multisampled conga pad projected only 0.42–0.57 on its own repeats.
    - *Status:* seeded; built into `measure_render.py`.
16. **An energy-jump detector needs an absolute gate and a local gate.**
    - *Evidence:* in run 1, noise-floor flicker gave −15 ms "errors". In the skill's self-test, filter
      pre-ringing before loud hits made extra onsets.
    - *Status:* seeded; built into `common.detect_onsets`.

## Live

17. **Check both dirty signals before any Live work:** Save Live Set enabled, and `AXEdited` on the close
    button. `song.can_undo` misses changes to the loop brace.
    - *Evidence:* run 1's first stop.
    - *Status:* seeded; built into `preflight.py` and `live_step.py`.
18. **Scan Log.txt for `Audio queue timeout` and time one LOM read.** A stalled engine makes writes take
    6.8 s, and only a restart fixes it.
    - *Evidence:* run 1's second stop.
    - *Status:* seeded; built into `preflight.py`.
19. **Make new sets with File > New Live Set, then Save As.** Never start from an older template.
    - *Evidence:* run 1, where Live's built-in template would not save in place.
    - *Status:* seeded; `live_step.py new` and `save-as`.
20. **Open dialogs by menu or AX press, and set names through AX.** A system prompt can swallow every
    keystroke, and Return or Escape could answer it. Steps that still type refuse while one is open.
    - *Evidence:* run 1. The same two prompts were still open on 12 October.
    - *Status:* seeded; built into `render.py`, `live_step.py save` and the `keys_safe` guard. `live_step.py
      dialog` and `press` (for unnamed alerts) are untested on a real alert: supervise their first use.
21. **Never wrap an export in an outer timeout.**
    - *Evidence:* run 1, where a killed Python left osascript holding the dialog.
    - *Status:* seeded; `preflight.py` lists orphans.

## Publishing

22. **Use one common gain per batch.** Aim for about −15 LUFS, or put glue on Main, rather than 7 dB of
    offline limiting.
    - *Evidence:* run 1. Per-file normalisation moved the sections 1 LU apart, and the limiter moved the
      kick's detected onset by 15 ms.
    - *Status:* seeded; built into `publish_prep.py`.
23. **Note length needs sustain.** With Operator's sustain at −inf and a 200 ms decay, an 8th sounds like
    a 16th.
    - *Evidence:* run 1's verifier measured every note 35–55 dB down by 122 ms.
    - *Status:* seeded; on the technique card.
