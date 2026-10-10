# TODO

Loose ends, last updated 1 October 2026. Remove items as they close.

## Rig and plugins

- [ ] Delete the stale duplicate plugins copied in from the T9 backup.
  Live loads the official copies in `/Library`. T9 keeps a backup.
  - `~/Library/Audio/Plug-Ins/VST/Dist COLDFIRE.vst`
  - `~/Library/Audio/Plug-Ins/VST3/kHs Transient Shaper.vst3`
- [ ] Add a plugin check to `lib/rig/start_headless.sh`.
  Read `~/Library/Application Support/Ableton/Live Database/Live-plugins-1.db`.
  Fail if a module has `scanstate` 3, which means the scan failed.
- [ ] A/B hotkeys are built (`hands ab`, `hands spectrum`, Hammerspoon ⌃⌥⌘ A/D/S/N).
  Hammerspoon is installed but waits on a first-launch prompt on screen.
- [ ] Move the arrangement pipeline (lead-in, cut, restore automation, render, measured trim, timeline check) from `hands/scripts/arrange_prototype` into `hands` proper.
  Delete Time drops envelopes whose breakpoints are all cut; see the ableton-guide skill.

Licensing now in place on the Mac mini: iLok (Soundtoys), Arturia Software
Center (COLDFIRE), SSL Download Manager (FlexVerb), Kilohearts Installer.

## HW002 Short (release by 31 October 2026)

- [x] References bought, loaded into `HW002_121_refs.als`, level-matched at −14 LUFS.
  Comparison and rubric seed: `docs/hw002/references.md`.
- [ ] Anthony listens against the rubric seed and corrects it.
- [ ] Arrangement references: listen to the label previews in `docs/hw002/arrangement-references.md`.
  Start with KSMS (vs the full *Roses*) and Remon Verhoeve's *Contradiction*.
- [ ] Pick from the arrangement experiments on /skrng: batch 2 (shapes after references) and batch 3 (hat progressions, under 40 s).
- [ ] Mix fixes the references point to: mono below 120 Hz, restore 25–40 Hz, lift 1–3.2 kHz, tame ~10 kHz, denser drum bus.
- [ ] Open interview items 7, 8, 9 and 11 wait on the references.
  They cover section choice, the bar-81 hit, pending mix changes and the loudness target.
- [ ] Item 12 is open: who masters.
- [ ] Remove or relabel the pre-plugin 30 s experiment on /skrng.

## Repo

- [ ] One Dependabot alert stays open: setuptools < 83 in `prototypes/audio-browser`.
  It is pinned below 81 because tensorflow_hub still imports `pkg_resources`.
  Drop the pin when the segment extra moves off tensorflow_hub.
- [ ] Letta feedback in `prototypes/letta-vibe/src/letta_vibe/vibe/server.py` has been dead code.
  It imports `letta.create_client`, which letta 0.7 removed. Port to `letta-client` if it is wanted.
- [ ] Commit Anthony's interview answers next to
  `docs/interviews/2026-09-30-what-next.md`.
- [ ] Site: a releases page with every release in one playlist.
