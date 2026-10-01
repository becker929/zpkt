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
- [ ] Document the forced rescan in the same skill.
  A plain rescan skips plugins that failed before.
  `touch` the binary in `Contents/MacOS`, then press Rescan.
- [ ] Install ffmpeg on the Mac mini (`brew install ffmpeg`).
  Without it, `mlab calibrate` skips 11 of 94 checks (codec round-trips).
- [ ] Install Hammerspoon and grant it Accessibility access.
  The A/B and spectrum hotkeys depend on it.

Licensing now in place on the Mac mini: iLok (Soundtoys), Arturia Software
Center (COLDFIRE), SSL Download Manager (FlexVerb), Kilohearts Installer.

## HW002 Short (release by 31 October 2026)

- [ ] References: Anthony sends DJ-set links and timestamps for tracks 2 and 3.
  Then identify, list for purchase, load, loudness-match and A/B.
- [ ] Rubric seed from `notes/music-active.md`, extended to all three references.
  Keep teacher and collaborator names out of this public repo.
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
