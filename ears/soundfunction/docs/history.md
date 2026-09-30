# History

What was built, in order. Times are UTC from the commit records of the two
repositories, plus the Mac agent's manifests. Elapsed times are what they
were, including the hung jobs and the sleeping machines, because those are
what future estimates have to include.

## Before this week

Anthony had an Ableton control skill already ("One Skill, Two Engines": OSC
via AbletonOSC, the Live Object Model via an MCP bridge, and a `hands`
package that turns a project config into Live actions). It existed before
5 September. Not knowing that is why the web session once estimated a year
for driving Live.

## 5 September (evening)

- Research section and the sound-function preliminary report online (20:32).
- Listening test page and its answer store, a Cloudflare Worker with KV (21:28).

## 6 September

- 01:54: part two. 300 freely licensed hard techno tracks measured; a library
  of 718 labelled one-shots (318 real from CC BY / public-domain packs, 400
  synthetic); a role classifier; a browser role meter. About 4.5 hours.
- 05:40: notes 1 and 2 (From a meter to an engineer; One producer, one pair
  of ears).
- 06:00: the private lab: gated uploads, stem-aware analysis reports, end to
  end tests. About 4 hours.
- 07:31: part three. The corpus separated into stems with Demucs. 1.5 hours.
- 17:57 to 20:37: deterministic separation, local-folder runner, Drive fetch,
  kicks located by beat-grid onsets, whole-beat kick measures, the bench
  sheet, a four-source model for the meter, a PCA embedding of corpus,
  references and Anthony's tracks.
- 21:42: note 3 (Where the tracks sit).
- 23:13 to 23:49: the hypotheses register with tests; loudness (BS.1770);
  H30 to H32; a second literature sweep; the part four generator; corpus
  round two merged with a genre filter. Notes 4 and 5 (Four horizons; The
  session).

## 7 September

- 06:01 to 08:17: advice sweep of tool makers and tutorials producing signal
  chains and H33 to H47; corpus doubled to 508 measured tracks, 650
  separated excerpts; part four published. 8.5 hours overnight including
  downloads.
- 19:33: the band-split pump measure and verdicts on H34, H38, H39, H42.
  The first run hung ten hours at 650 of 662 with nothing written; rewritten
  with a per-file alarm, resume and incremental saves. 11 hours elapsed, of
  which about one was compute.
- 23:55: note 6 (The split that is not there), 411 words.

## 8 September

- 00:10: the list of first experiments for when Live can be driven (E1 to E5).
- On the Mac, the knob-measure rig: two knobs on the SNTS Style track's Kick
  (G) swept and measured. Decapitator Drive non-monotonic with a crest hump
  near 0.6 to 0.625 and a sub-share trough at 0.6; StandardCLIP threshold a
  clean invertible crest control. About one day of rig time. Zipped 9 Sep
  01:21.

## 9 September

- 01:33: note 7 (The knob that lied about being simple); `research/knob-map.md`.
- 01:33 to 03:41: the decay bug found and fixed (decay_ms and duration_s
  were reading pitch, not time); the listening test rebuilt on real
  CC-licensed one-shots (40% out of range down to 15%); the two Live job
  specs (multitrack bounce, one-shot pack). Two hours.
- 03:41 onward, on the Mac: the multitrack bounce. First stem 30 minutes after
  the spec was published. A Hammerspoon config interfered with Live and baked
  dropouts into takes; the Mac slept once and froze the transport; one SNTS
  track was confirmed silent at source. Clean archive of 18 stems from two
  sets at 11 Sep 04:44. Two days.

## 11 September

- The research repository given a durable home: squashed, audio excluded,
  pushed as branch `sound-function-research` on `becker929/anthonybecker.me`.
- The multitrack archive fetched (502 MB), analysed, deleted from the
  container. The corpus pump measure shown to saturate near 12 to 14 dB and
  to break on solo stems, with two controls. Notes 8, 9, 10 published.
- Note 10 rewritten as "The plan, with dates" after Anthony's feedback:
  goal first, thirteen requirements with calibrated dates, a glossary,
  plainer prose. `research/next.md` written.
- The lab moved to the Mac: `requirements.txt`, `lab/duck_calibration.py`
  (corpus, calibrate, bypass modes), `research/mac-lab.md`.
- Shared channels built: an ntfy topic with three levels and a Mac-side
  Reminders mirror; a mailbox pull request (#25) with the web session
  subscribed and a three-hourly fallback Routine; Mac-side poller. The first
  topic name leaked into the public mirror and was rotated.
- 17:10: PR #25 opened, subscribed, Routine armed.

## 12 September

- 04:24: the Mac agent's first mailbox reply. Channel works end to end.
  Reminders mirror refused by its permission layer (a human step); the export
  dialog blocked on Accessibility (told to use the tap instead).
- 06:24: `live_rumble_bypass_v1` delivered. LFOTool is one broadband duck to
  silence; both bands dip at the same instant; no split. H34 answered on one
  real track. Two corrections found: the multitrack stems were 57% trailing
  silence, and two takes must be aligned before dividing.
- Register, results page, bounce spec and note 8 updated; the bypass tool
  now aligns and measures content length.
- The Mac poll never fired on the next job. Cause: `claude` lives in
  `~/.local/bin`, which the launchd PATH lacked. Fixed with logging.
- pedalboard adopted for plugin sweeps outside the DAW: `lab/plugin_sweep.py`
  tested at over a thousand times real time; `research/offline-plugins.md`.
- The mandate moved to the Mac. This documentation written.
- 13:08 to 16:21: the kick-group knob map (`knobmap_hw002_kickgroup_v1`,
  ten rows: Roar bypassed, compressor idle, Threshold live) and the follow-up
  at operating point 0.4 (`_v2_thr040`: Ratio inverts above 0.33). Rows 4 to
  16 recorded. Calibration of the remaining measures designed with cases and
  tolerances; the Mac is building it. Roar-on pack started on the rig.
- 18:11: note 11 (Three days, timed) published, dated and time-stamped, at
  Anthony's request. Standing rule from him: publish to the site proactively;
  it is his main window on the project.
- 13:07 to 13:09: `knobmap_hw002_kickgroup_v3_roar_on` (Roar's Device On
  forced to 1: bus sub share 0.90 to about 0.77, the biggest single move in
  the map; Drive 2.3 dB of crest, Tone Amt a colour control, Blend flat and
  unexplained) and `calibrate_measures_v1` (requirement 2, five measures
  against known answers): grid lock, sustain share, band shares off the
  edges and crest under clipping all pass; `decay40_ms` fails all 12 rows,
  under-reading by 17 to 37% with a frequency-dependent bias, so a deeper
  kick reads as a shorter kick, needing a fix in the measure. Three
  meanings of "sub" now documented with numbers: the library's six-band
  `sub` (20-60), the knob map's collapsed `sub_share` (20-150, sub plus
  low), and the ears shim's two-way split.
- 20:10: Anthony granted the Mac agent the register and the site directly,
  closing the question it had put to him on the 12th. The web session's
  docs entry is above; see Decisions for the exact wording.

| kind of work | observed |
|---|---|
| a new measure, corpus run and write-up | 2 to 8 hours |
| a note | about 1 hour |
| a Live job, spec to first output | under 1 hour |
| a Live job, first output to a checked archive | 1 to 2 days |
| corpus doubling with downloads | 8.5 hours overnight |
| a bent instrument found per contact with real material | roughly one per day |
| listening-test answers, unprompted | 3 in 6 days, one sitting |
