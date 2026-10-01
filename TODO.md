# TODO

Loose ends as of 30 September 2026. Remove items as they close.

## Rig and plugins

- [ ] Delete the stale duplicate plugins copied in from the T9 backup.
  Live loads the official copies in `/Library`. T9 keeps a backup.
  - `~/Library/Audio/Plug-Ins/VST/Dist COLDFIRE.vst`
  - `~/Library/Audio/Plug-Ins/VST3/kHs Transient Shaper.vst3`
- [ ] Add a plugin check to `lib/rig/start_headless.sh`.
  Read `~/Library/Application Support/Ableton/Live Database/Live-plugins-1.db`.
  Fail if a module has `scanstate` 3, which means the scan failed.
- [ ] Add "plugin sources off" to the silent-bounce ladder in
  `hands/.cursor/skills/ableton-guide/SKILL.md`.
  Live shipped with every plugin source off, so nothing was scanned.
- [ ] Document in the same skill: opening a set over unsaved changes raises a hidden
  "Save changes?" dialog, and LOM keeps editing the old set. Check the window title first.
- [ ] Document the forced rescan in the same skill.
  A plain rescan skips plugins that failed before.
  `touch` the binary in `Contents/MacOS`, then press Rescan.

Licensing now in place on the Mac mini: iLok (Soundtoys), Arturia Software
Center (COLDFIRE), SSL Download Manager (FlexVerb), Kilohearts Installer.

## HW002 Short (release by 31 October 2026)

- [x] References bought, loaded into `HW002_121_refs.als`, level-matched at −14 LUFS.
  Comparison and rubric seed: `docs/hw002/references.md`.
- [ ] Anthony listens against the rubric seed and corrects it.
- [ ] Arrangement references: listen to the label previews in `docs/hw002/arrangement-references.md`.
  Start with KSMS (vs the full *Roses*) and Remon Verhoeve's *Contradiction*.
- [ ] A/B hotkeys are built (`hands ab`, `hands spectrum`, Hammerspoon ⌃⌥⌘ A/D/S/N).
  Hammerspoon is installed but waits on a first-launch prompt on screen.
- [ ] Mix fixes the references point to: mono below 120 Hz, restore 25–40 Hz, lift 1–3.2 kHz, tame ~10 kHz, denser drum bus.
- [ ] Open interview items 7, 8, 9 and 11 wait on the references.
  They cover section choice, the bar-81 hit, pending mix changes and the loudness target.
- [ ] Item 12 is open: who masters.
- [ ] Remove or relabel the pre-plugin 30 s experiment on /skrng.
  The 60 s demo with all plugins is published as `2026-09-30-hw002-60s-demo`.
  Its set is `~/_agent_scratch/HW002/HW002_121_60s.als`.

## Repo

- [ ] One Dependabot alert stays open: setuptools < 83 in `prototypes/audio-browser`.
  It is pinned below 81 because tensorflow_hub still imports `pkg_resources`.
  Drop the pin when the segment extra moves off tensorflow_hub.
- [ ] Letta feedback in `hands/src/hands/vibe/server.py` has been dead code.
  It imports `letta.create_client`, which letta 0.7 removed. Port to `letta-client` if it is wanted.
- [ ] Commit Anthony's interview answers next to
  `docs/interviews/2026-09-30-what-next.md`.
- [ ] Site: a releases page with every release in one playlist.
