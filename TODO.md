# TODO

Loose ends, last updated 12 October 2026. Remove items as they close.

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

## Hands gaps from learn-tutorial

The first tutorial practice (run 1, 11 October 2026) found these gaps. The skill works around each one in
`.claude/skills/learn-tutorial/scripts/`. Move each into `hands` and delete the workaround.

- [ ] `session.is_dirty()`: File > Save Live Set enabled, or `AXEdited` on the close button.
  `song.can_undo` misses loop-brace changes. Workaround: `live_step.py edited`, `preflight.py`.
- [ ] An audio-health preflight that does not play: `Audio queue timeout` in Log.txt, plus one timed
  harmless write. A stalled engine took 6.8 s per write. Workaround: `preflight.py`.
- [ ] `new_set()` (File > New Live Set) and `save_as(dir, name)`. Live's built-in template is from an
  older Live and cannot be saved in place. Workaround: `live_step.py new` and `save-as`.
- [ ] Export by a menu press or AX press instead of Cmd+Shift+R; set the file name through AX. Read the
  Save panel's folder back through AX before pressing Save, and report where the file really landed.
  A system prompt swallowed the keys. Workaround: `render.py` patches the two lines at run time.
- [ ] `knobs.set_display(param, "200 ms")`: bisect `str_for_value` to a display target. Live's display
  truncates, so aim for the lower edge.
- [ ] `reap_modals` reports unnamed dialogs (size, element count) and asks for a screenshot instead of
  skipping them. Live's own alerts expose no text.
- [ ] `session.check` for practice sets. "Ours" means only the `set_prefixes` in rig.toml; let a run
  name the set it created. Workaround: `live_step.py --expect`.
- [ ] `hands plan` renders leave their set dirty: the loop brace is changed and never saved. Restore or
  save the set when done.
- [ ] Arrangement automation, or another way to gate devices that make sound on their own (Vinyl
  Distortion crackles with no input). Workaround: render the device's output once into an audio clip.

## Repo

- [ ] One Dependabot alert stays open: setuptools < 83 in `prototypes/audio-browser`.
  It is pinned below 81 because tensorflow_hub still imports `pkg_resources`.
  Drop the pin when the segment extra moves off tensorflow_hub.
- [ ] Letta feedback in `prototypes/letta-vibe/src/letta_vibe/vibe/server.py` has been dead code.
  It imports `letta.create_client`, which letta 0.7 removed. Port to `letta-client` if it is wanted.
- [ ] Commit Anthony's interview answers next to
  `docs/interviews/2026-09-30-what-next.md`.
- [ ] Site: a releases page with every release in one playlist.
