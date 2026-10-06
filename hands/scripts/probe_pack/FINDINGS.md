# Probe packing: findings

Study date: 2026-10-06. Ableton Live 12.4.6. The scripts are in this folder.

## 1. Question and setup

**Question.** How do we render many probes as cheaply as possible?

A probe is one variant of an HW002 section. The tempo is 160 BPM. One bar lasts 1.5 s, so a 20-bar probe is 30 s of audio.

**Anthony's model.** A batch holds renders. A render packs submixes and patterns.

- A *submix* is a vertical copy of the set content. S counts them.
- A *pattern* is a horizontal time slice. P counts them.
- Predicted bottlenecks, slowest first: set load/unload, editing, rendering, memory.

**Setup.**

- Live 12.4.6 on a 16 GB Apple-silicon Mac.
- `zpkt/hands` drives Live. LOM calls cost about 0.85 s each through the bridge.
- Menus and dialogs are driven through AppleScript.
- Renders are offline exports through Live's Export dialog, unless noted.
- The test set has a kick group and a perc group: 7 tracks, one submix.
- A 2-bar lead-in comes before the 20-bar shape. One export of it is 33 s.
- Each timed step appends a row to `~/_agent_scratch/probepack/bench.jsonl`.
- Logged times are wall clock per step. Guard checks between steps are excluded. They add about 3 s per batch.

| Run | What it tests | Script |
|---|---|---|
| Phase 1 | load, save, LOM, Edit-menu time ops, real-time record | `bench_primitives.py`, `bench_renders.py` |
| Vertical | S = 1, 2, 4 copies; reload; export all tracks | `bench_vertical.py` |
| E1 | memory and export vs S, after fresh restarts | `bench_e1_memory.py` |
| E2 | reuse the S = 4 set: LOM edit + export, no reload | `bench_phase3.py reuse` |
| E3 | horizontal: Duplicate Time to P = 1, 2, 4; export Main | `bench_phase3.py horiz` |
| E4 | Bounce Groups to New Tracks as the renderer | `bench_e4_bounce.py` |
| E5 | P = 16 × 20 bars; per-pattern automation written into the .als | `bench_e5_als.py`, `als_probe.py` |
| E6 | P = 32 × 8 bars with the reusable kit | `probe_kit.py` |
| E7 | a hill climb in Live: 32 candidates per batch | `climb_live.py`, `score_patterns.py` (ears/mlab) |

## 2. Measured primitives

Seconds of wall clock, from the log.

| Primitive | Median | Mean | n | Range | Note |
|---|---|---|---|---|---|
| One LOM call, any content | 0.89 | 0.88 | 22 | 0.72–1.37 | includes batched edits |
| 50 parameter sets as 50 calls | 42.6 total | – | 1 | – | 0.85 s per call |
| 50 parameter sets in one call | 0.76 | – | 1 | – | batching makes edits almost free |
| Insert a device (Reverb) | 0.83 | 0.84 | 3 | 0.73–0.96 | |
| Delete a device | 0.72 | 0.79 | 3 | 0.72–0.92 | |
| Duplicate a group track | 2.38 | – | 1 | – | |
| Write automation into the .als (Python, offline) | 0.83 | 0.83 | 3 | 0.82–0.85 | |
| Duplicate Time (GUI) | 6.96 | 7.27 | 12 | 6.77–8.17 | same cost from 2 to 160 bars |
| Delete Time (GUI) | 8.00 | 8.00 | 2 | 7.92–8.07 | |
| Save the set | 0.73 | 0.90 | 7 | 0.58–1.70 | one 19 s save that never wrote is excluded |
| Load, S = 1 (any P) | 5.09 | 5.13 | 10 | 4.15–7.07 | flat in P |
| Load, canonical set (unstripped) | 7.24 | 7.39 | 6 | 7.13–7.87 | 3 extra muted groups |
| Load, S = 2 / 4 / 8 | 7.8 / 13.8 / 25.8 | – | 1 / 3 / 1 | S = 4: 12.8–18.4 | grows a little faster than S |
| Restart Live | 11.2 | 11.2 | 2 | 7.56–14.84 | boot alone 4.5 s |
| Export Main, P = 1 × 20 bars (33 s audio) | 16.9 | – | 1 | – | |
| Export Main, P = 2 / 4 × 20 bars | 20.1 / 23.8 | – | 1 each | – | |
| Export Main, P = 16 × 20 bars (483 s audio) | 60.1 | 60.1 | 2 | 56.3–63.9 | |
| Export Main, P = 32 × 8 bars (387 s audio) | 51.9 | 52.4 | 2 | 51.9–53.0 | |
| Export all tracks, S = 1 | 21.4 | 21.4 | 5 | 18.8–23.6 | |
| Export all tracks, S = 4 | 37.4 | 37.8 | 5 | 37.3–39.1 | |
| Export all tracks, S = 8 | 59.7 | 59.7 | 2 | 58.8–60.7 | warm 12 GB and fresh |
| Bounce Groups to New Tracks, 2 groups × 30 s | 6.89 | 6.91 | 6 | 6.81–7.08 | no Save panel |
| Bounce loop per probe (edit, select, bounce, checks) | 14.5 | 14.5 | 4 | 14.3–14.6 | |
| Real-time resampling record, 33 s | 51.6 | – | 1 | – | 1.56× real time |

## 3. Methods compared

Seconds per probe = logged steps of one batch ÷ probes in it.

| Method | Run | Probes per render | s per probe | Live memory | Determinism and controls |
|---|---|---|---|---|---|
| Real-time resampling | Phase 1 | 1 | 51.6 | S = 1 | not checked |
| Vertical: fresh load + export all tracks | E1 | S = 1 / 4 / 8 | 29.1 / 13.0 / 10.8 | 1.8 / 5.3 / 9.5 GB | Exact. Copies in one pass null to −129 dB. |
| Vertical: warm reload + export all tracks | Vertical | S = 1 / 2 / 4 | 27.2 / 17.0 / 12.8 | not logged | as above |
| Vertical reuse: LOM edit + export, no reload | E2 | S = 4 (3 varied, 1 control) | 9.6 per submix; 12.8 per varied probe | 7.6 GB | Exact within a pass. Across passes the perc group differs; features agree. |
| Horizontal: Duplicate Time + export Main | E3 | P = 1 / 2 / 4 | 16.9 / 10.0 / 5.9 | S = 1 | No per-pattern variation. LOM cannot write arrangement automation. |
| Bounce Groups to New Tracks, one per probe | E4 | 1 | 14.5 | 4.5 GB | Kick group bit-identical to Export. Mutes and splits the source clips. |
| **Horizontal + .als automation, 20-bar** | **E5** | **P = 16** | **3.9 / 4.4** (4.1 / 4.5 with guards) | **4.7 GB, flat in P** | Features only. Same setting at 8 positions agrees within 0.01 dB. |
| **Horizontal + .als automation, 8-bar** | **E6** | **P = 32** | **1.78** | **4.7 GB, flat** | Same setting at 16 positions agrees within 0.02–0.03 dB (2–8 kHz level). |

Notes:

- E1 excludes the restart. A restart per batch adds 7.6–14.8 s.
- E2 pays one 18.4 s load before its rounds.
- E3 adds 8 s per doubling, once. E5 adds a template build of about 40 s, once; E6 about 80 s (P = 32).
- Memory is Live's footprint, compressed pages included. E1 is measured right after a restart.
- E2, E4, E5 and E6 ran in a warm session. A fresh S = 1 load uses 1.5 GB. A warm one sits at 4.5 GB.
- In an E5 batch, export takes 87–88 % of the time. Load takes 7–8 %. Guards take 4 %. The .als write takes 1 %.

The key contrast:

- An extra submix costs 5.3 s per 33 s of audio (all-tracks export).
- An extra pattern costs about 3.2 s per 33 s of audio (Export Main).
- An extra submix also costs about 0.9 GB. An extra pattern costs no memory.

## 4. Cost model

Symbols: S submixes, P patterns, L bars per pattern.
A is the audio length of one render in seconds: A = 1.5 · (2 + P · L).
That is a 2-bar lead-in plus P patterns with no gaps.

**General form.**

```
tau(S, P, L) = [ t_edit + t_load(S) + t_guard + t_export(S, A) ] / (S · P)

Export Main (S = 1):  t_export = a + b · A
Export all tracks:    t_export = e0 + e1 · S · (A / 33)     # A-scaling assumed; measured only at A = 33 s
Load:                 t_load(S) = l0 + l1 · S                # flat in P
Memory:               M(S) = m0 + m1 · S  GB                 # flat in P
```

With reuse (E2), drop t_load from each batch and pay it once.

**Recommended method (S = 1, Export Main).** The terms collapse to:

```
tau(P, L) = F / P + c · L
F = t_write + t_load + t_guard + a + 3·b = 22.4 s per batch
c = 1.5 · b = 0.145 s per bar
```

So a 20-bar probe can never cost less than 2.9 s, and an 8-bar probe not less than 1.2 s.

The template is a one-time cost:

```
C(P) = t_load + t_trim + log2(P) · t_dup + t_save = 13.8 + 6.94 · log2(P)  s
```

Over B batches that share one template, add C / (B · P) per probe.

**Fitted constants.**

| Constant | Value | How | n | Fit quality |
|---|---|---|---|---|
| a, Export Main fixed cost | 13.2 s | least squares, Export Main vs A (E3 + E5) | 5 | rms 2.5 s, R² 0.984 |
| b, Export Main per audio second | 0.097 s/s (10× faster than real time) | same fit | 5 | |
| a, b from E3 only (P ≤ 4) | 14.8 s, 0.074 s/s | least squares | 3 | rms 0.4 s |
| e0 + e1·S, export all tracks (A = 33 s) | 18.2 + 5.3·S s | least squares, E1 fresh | 3 | rms 0.2 s |
| same, all 13 export-all rows | 15.8 + 5.5·S s | least squares | 13 | rms 1.2 s |
| l0 + l1·S, load | 2.0 + 2.9·S s | least squares, E1 + vertical loads | 6 | rms 0.45 s; quadratic term +0.06·S² |
| t_load, S = 1, any P | 5.09 s | median | 10 | |
| t_write, .als automation | 0.83 s | mean | 3 | |
| t_guard, checks per batch | 3.0 s | row timestamps minus logged steps | 2 | 2.7 and 3.0 s |
| t_dup, Duplicate Time | 6.94 s | median of kit rows | 8 | all 12 rows: median 6.96 s |
| t_trim, Delete Time | 8.0 s | mean | 2 | |
| t_save | 0.73 s | median | 7 | |
| m0 + m1·S, memory after load | 0.74 + 0.87·S GB | least squares, E1 fresh | 3 | rms 0.09 GB |
| memory after export | 0.80 + 1.09·S GB | least squares, E1 fresh | 3 | rms 0.08 GB |

E5 exported slower than the E3 line predicts: 56–64 s against 50.7 s. E5 added a Reverb, which may explain part of it.

E6 checks the model at a new point. Predicted export for 387 s of audio: 13.2 + 0.097 · 387 = 50.7 s. Measured: 51.9 s.
Predicted cost per 8-bar probe at P = 32: 1.9 s. Measured: 1.78 s. Render cost does scale with audio length.

Consistency check: at S = 8 the general form gives 11.2 s per probe. E1 measured 10.8 s, plus 0.4 s of guards.

**Predictions for the recommended method.** Seconds per probe, steady state, template excluded.
The full table, with ranges, is in `~/_agent_scratch/probepack/cost_model.json`.

| P | 20-bar patterns | 8-bar patterns | Template, once |
|---|---|---|---|
| 1 | 25.3 | 23.6 | 13.8 s |
| 4 | 8.5 | 6.8 | 27.7 s |
| 8 | 5.7 | 4.0 | 34.6 s |
| 16 | 4.3 (measured 4.1–4.5) | 2.6 | 41.5 s |
| 32 | 3.6 | 1.9 (measured 1.78) | 48.5 s |
| 64 | 3.3 | 1.5 | 55.4 s |

Vertical packing has a worse floor. With reuse, export alone tends to 5.3 s per probe. Memory caps S near 8–10. So vertical bottoms out near 8 s per probe at S = 8.

## 5. Verdicts on the predicted bottlenecks

Measured order, slowest first: rendering, then load, then editing (when batched), then memory.

| Predicted rank | Bottleneck | Verdict | Number |
|---|---|---|---|
| 1 | Set load/unload | Refuted as the top cost; nuanced for vertical | E5: 5.1 s per batch = 0.32 s per probe, 7 % of the batch. Vertical: +2.9 s per submix, 30 % of the S = 8 batch. |
| 2 | Editing | Nuanced | Batched LOM call 0.89 s; .als write 0.83 s; 1 % of a batch. GUI time ops cost 7–8 s each. |
| 3 | Rendering | Refuted: it is the main cost | Export Main = 13.2 s + 0.097 s per audio second. 87–88 % of an E5 batch. |
| 4 | Memory | Confirmed for horizontal; a hard cap for vertical | Flat in P (4.5 → 4.7 GB from P = 1 to 32). Vertical: +0.87 GB per submix, cap S ≈ 8–10. |

**Load/unload.** A stripped S = 1 set loads in 5.1 s. Load does not grow with P. Unload has no separate cost: opening the next set replaces the current one. The save before a switch costs 0.6–1.7 s. Load only matters for vertical packing. There it grows slightly faster than S: 5.4, 12.8, 25.8 s at S = 1, 4, 8.

**Editing.** A bridge call costs about 0.85 s, whatever it does. Fifty edits in one call took 0.76 s. The same fifty as separate calls took 42.6 s. So editing is cheap only when batched or done offline. GUI edits are the expensive kind: Duplicate Time and Delete Time take 7–8 s each. The recommended method uses them only to build the template.

**Rendering.** This is the real bottleneck. Every export pays about 13 s of fixed cost: dialog, Save panel, fixed delays, file polling. Then it costs about 0.1 s per second of audio. At P = 16 the export is 87 % of the batch. The per-second cost sets the floor: 2.9 s per 20-bar probe, 1.2 s per 8-bar probe.

**Memory.** Least binding, as predicted, but only for horizontal packing. Each submix adds 0.87 GB after load and 1.09 GB after export. That caps S at 8–10 on 16 GB. Memory pressure never slowed a render: S = 8 exported in 58.8 s at a warm 12 GB footprint and 60.7 s fresh.

## 6. Recommended method

Horizontal packing with automation written into the .als (E5, E6). S = 1. The code is `probe_kit.py`.

1. Build a template once per shape and P (`probe_kit.template`). Trim the set to the shape. Run Duplicate Time log2(P) times. Save. About 40 s at P = 16, 80 s at P = 32.
2. Per batch, in Python (`probe_kit.write_batch`): copy the template. Add donor devices. Write one step envelope per varied parameter, one level per pattern. Run `als_probe.check`. 0.8 s.
3. Load the batch set, export Main once, slice it per pattern (`probe_kit.render`).
4. Put control patterns in every batch. Compare features, not samples.

Evidence that it works:

- Reverb Dry/Wet stepped per pattern gave monotonic feature changes.
- The 2–8 kHz level fell from −30.7 to −36.7 dB as Dry/Wet went from 0 to 0.75.
- The same setting at 8 different positions agreed within 0.01 dB (20-bar), and at 16 positions within 0.03 dB (8-bar).
- The effect repeated across batches: −3.70 vs −3.71 dB.
- Live's memory stayed flat at 4.7 GB.

Why it wins:

- One load and one export fixed cost are shared by P probes.
- A pattern costs less render time than a submix, and no memory.
- Edits happen offline. They need no LOM call and no GUI.

### Scoring probes: calibrate the position noise

Modulated plugins (LFOTool, Shifter, Hybrid Reverb, Grain Delay) differ by song position.
Features they touch move a little from pattern to pattern, even with identical settings.
On the 8-bar kit, the noisiest were transient contrast (±0.28 dB), the 25–31 Hz bands (±0.6 dB), block crest and 500–2000 Hz correlation.

A score with a strict guard ("no feature may get worse") turns that into noise: identical settings spread by 0.29 in score.
`score_patterns.py calibrate` measures each feature's spread on identical patterns. The guard then ignores worsening inside 1.5 × that spread.
That cut the spread of identical settings to 0.03 for the "space" score. A climber should only accept improvements larger than that.

### Limits

- **No sample-exact controls across patterns.** Each pattern sits at a different song position.
  - Modulated plugins differ by position. Tails from one pattern ring into the next.
  - Only features agree. Use controls in the same batch, calibrate the noise, and compare features.
  - For sample-exact controls, use vertical submixes in the same pass instead.
- **Pattern boundaries.** Patterns abut with no gap. The scorer skips the first bar of each pattern. Bleed beyond that is not measured yet.
- **Main only.** Export Main gives one stereo mix. Group stems need an all-tracks export, which costs more per second. Main equals the sum of the groups × the main fader exactly (−127.6 dB).
- **Duplicate Time quirks.**
  - Each call takes 7–8 s, whatever the length.
  - It doubles the region, so P is a power of two.
  - It copies automation too. Trim the set to the shape first, and write probe automation afterwards.
  - A breakpoint just past the shape (beat 89) broke the song-end check in `timeops.duplicate`. The kit checks the song end and the clip count instead. Clips that straddle the lead-in boundary must be counted by overlap.
  - The menu item can be disabled for a moment. The kit retries up to 6 times.
- **Group-device envelopes only through the .als.**
  - LOM cannot write arrangement automation. `Clip.automation_envelope` refuses arrangement clips.
  - Group tracks hold no clips, so their devices have no clip envelope at all.
  - `als_probe.py` edits the XML directly and renumbers Pointee ids.
  - A new device needs a donor copy from another set. Here a Reverb came from the S = 4 set.
  - The .als format is undocumented (schema "12.0_12402"). Recheck it after Live updates.
- **What still needs the GUI.**
  - The Export dialog, once per batch. It is most of the 13 s fixed cost.
  - Duplicate Time, Delete Time and Save, for the template.
  - The arrangement time selection for the export range.
- **Disk.** 32-bit float WAV grows with audio length: 170 MB at P = 16 × 20 bars.
- **Warm sessions.** Memory accumulates across loads: 1.5 GB fresh vs 4.5 GB warm at S = 1. Restart every few batches (7.6–14.8 s).

### When to use something else

- **Vertical submixes** when a probe needs a sample-exact control in the same pass. Keep S ≤ 8.
- **Bounce** when one short render must avoid the Save panel. It costs 14.5 s per probe and edits the source clips. One LOM call undoes that. Paste Bounced Audio could not be reached through the menus.
- **Real-time recording** never: 51.6 s for one probe.

## 7. Safety lessons from running it

- Keep each LOM call under the bridge's 12 s timeout. Fourteen group duplications in one call ran past it, Live kept working, and the next step met a "Save changes?" prompt.
- Check for dialogs before and after every Live step (`pp.check`). Stop on anything unexpected; do not chain steps past a surprise.
- An export can fail in its last second while the files are complete. Count the files before retrying, and never export over existing files: Live trashes them and renames the new ones.
- After a quit, macOS can still report Live as running for a moment, and `open` then fails (-600). Wait for LaunchServices before relaunching.

## 8. Open questions and next experiments

1. **Lean export script.** Skip popups that are already set. Poll every 0.1 s instead of fixed delays. About 13 s of the fixed cost is the script's own waiting.
2. **Larger P.** Run P = 64 and 128 at 8 bars. Check export linearity, file size and slice alignment.
3. **Multi-parameter and multi-device probes.** Several envelopes per pattern, rack-nested and group devices.
4. **Template built offline.** Copy clips and envelopes in the XML instead of Duplicate Time.
5. **Hill climber in Live (E7, E7b): the loop works; the "space" objective does not.**
   - One batch = one generation: pattern 0 re-renders the current best as a control, 31 candidates.
   - E7, Reverb inserted on the perc group (Dry/Wet is a crossfade): 10 generations, 320 probes, 710 s. About 2.2 s per probe including scoring. It plateaued at the original.
   - E7b, Reverb 100 % wet on a return, perc-group send automated (the batch 5 shape, done in Live): a first generation sampled the whole space. The best of 31 beat the control by 0.015; the noise margin is 0.03. Not continued.
   - Render cost depends on the devices, not just the audio length: 31 random large reverbs took 194 s to export instead of 53–58 s.
   - Reading: the perc group sits about 14 dB under the kick, so reverb on it hardly moves the full mix's stereo features. With calibrated position noise, batch 5's offline "space" gain (+0.07) would sit near the noise floor, yet Anthony preferred it by ear. For "space", the reference-feature objective does not capture what he hears. Next: put his listening in the loop, or find a feature that tracks it.
6. **"Selected Tracks Only" export** for vertical packing. Does it cut the 5.3 s per submix?
7. **CPU during export.** Does Live render on one thread? That decides whether anything can run in parallel.

## 9. Where the numbers come from

- **Least-squares fits from log rows:** Export Main a and b; export-all e0 and e1; load l0 and l1; memory m0 and m1.
- **Medians and means from log rows:** every row of the primitives table. t_guard comes from row timestamps.
- **From the experiment reports, not the log:** the null and determinism results (−129 dB, −127.6 dB, the about −6 dB perc-group residual across passes, the deterministic kick group on the first export after a load); the E5 and E6 feature results; E4 behaviour; LOM refusing arrangement automation; the practical cap of S ≈ 8–10.
- **Background research:** `~/_agent_scratch/probepack/research/R1-rendering-options.md`.
- **Model file:** `~/_agent_scratch/probepack/cost_model.json`.
