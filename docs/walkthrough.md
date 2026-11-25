# Walkthrough: check by hand what the upgrade could not test offline

The November 2026 upgrade (branch `upgrade/integrate`) kept every capability, and offline tests cover most of them.
This walkthrough covers the rest: whatever needs Live, the MiniLab, the network, a real model, or ears.
Each step has the command or the click, and what you should see.

**An agent runs this walkthrough first, before handing it to Anthony.** The agent does every [auto] and [gui] step
itself, fills the checklist at the end, fixes what fails or reports it, and only then hands Anthony the few [you]
steps in one short session. Anthony should never be the first to find a failure.

- **[auto]**: the agent does it with the shell, HTTP or Live, and reads the result.
- **[gui]**: the agent does it in a browser (the in-app browser pane) or by driving the screen (computer use). It
  checks what it sees with the page's text and state first, and with small screenshots only where the look matters.
  If the step also says "hear", the agent checks what it can measure (playback position, meter levels, loudness),
  and lists the listening part for Anthony.
- **[you]**: it needs Anthony's hands on the MiniLab, his ears, or his decision. The agent prepares it (Live, the
  page and the set ready) and asks.

Rules for the agent:
- Live plays through the Mac's speakers, so Anthony may hear it. Live steps go one checked step at a time, never as
  an unattended chain.
- Never press a thumb, heart, vote or rating on Anthony's real data (the artist's feedback, the image wall's votes).
  Check that the control is there and works with test data or a temporary folder. Taste data is his.
- Steps that cost money (Gemini sessions, one generated image) are fine once each. Say what they cost in the
  handoff.
- At most 6 screenshots per thread, captured small (AGENTS.md).

Do the parts in order. The table at the end is for ticking them off.

## Safety first

1. **Never on HW002_121_pp_finish while it has unsaved changes.** Step 4 is yours: save it or keep the changes
   aside yourself. No agent saves, opens over, or reloads that set.
2. **Work on a copy.** Step 6 makes `HW002_121_pp_walk`. The e2e test rig (`~/_agent_scratch/zpkt-e2e`, sets
   `zpkt_e2e_*`) is not on this Mac now: its link points at a folder on the offload disk that is not there. If in
   doubt, make a copy.
3. **One Live step at a time.** After each Live step, run `uv run zpkt live modals`. It should say `CLEAN`. If a
   dialog is open, look at Live and answer it yourself.
4. **These commands save the set in front:** `zpkt live open` (without `--no-save`), `zpkt live save`,
   `zpkt live rig reset` (without `--discard`), and the demo's `livectl.py open`. Never run them while
   HW002_121_pp_finish is in front.
5. **One mix desk at a time.** Only one desk can hold the MiniLab and UDP ports 8986 and 8987. Stop the running one
   before you start another (step 7). The desk also follows whatever set is in front, so stop it before you open
   the arranger's sets.
6. **Another agent may share Live.** The preflight warns when a Gemini CLI process runs. Finish or stop it first.

## Servers: how to stop and start each

The repo's environment is now one `.venv` at the root, made by `uv sync --all-extras`. `hands/.venv` and
`ears/.venv` are no longer used. Old restart recipes that name them work only for the old checkouts.

| Server | Port | Stop | Start |
|---|---|---|---|
| Mix desk, from zpkt-main | 8985, UDP 8986/8987 | `pkill -f 'zpkt-main/contrib/mixdesk/server.py'` | `cd ~/Desktop/zpkt-main && (nohup zsh -c 'while true; do ~/Desktop/zpkt-main/hands/.venv/bin/python ~/Desktop/zpkt-main/contrib/mixdesk/server.py; sleep 2; done' >> ~/_agent_scratch/mixdesk-server.log 2>&1 &)` |
| Mix desk, from zpkt-upgrade | the same | `pkill -f 'zpkt-upgrade/contrib/mixdesk/server.py'` | `cd ~/Desktop/zpkt-upgrade && (nohup zsh -c 'while true; do ~/Desktop/zpkt-upgrade/.venv/bin/python ~/Desktop/zpkt-upgrade/contrib/mixdesk/server.py; sleep 2; done' >> ~/_agent_scratch/mixdesk-server.log 2>&1 &)` |
| Arranger, walkthrough copy | 8976 | Ctrl-C in its tab | step 74 |
| Harness (the running one) | 8787 | `hs -c 'HARNESS.stop()'` (Hammerspoon supervises it, from `~/Desktop/zpkt`) | `hs -c 'HARNESS.start()'` |
| Harness, walkthrough copy | 8877 | Ctrl-C in its tab | step 84 |
| Checklist prototype | 8798 | Ctrl-C in its tab | step 94 |
| Image wall | 8796 | Ctrl-C in its tab | step 99 |
| Zpkt web | 8789, 8797 | not needed | `launchctl kickstart -k gui/$(id -u)/me.anthonybecker.zpkt-web` restarts it |

Each `pkill` stops the restart loop and the server together. If `pgrep -fl mixdesk/server.py` still shows one after
3 s, run the `pkill` again. A desk that starts does not replace the pager already loaded in Live: after every start,
run `curl -s -X POST http://127.0.0.1:8985/api/restart`. It loads the new checkout's `pager.py` into Live.

The walkthrough copies of the arranger and the harness use their own ports, so the running ones keep serving.

---

## Part 1. Setup and preflight

**1. [auto] The checkout.**
`cd ~/Desktop/zpkt-upgrade && git status -sb`
You should see: `## upgrade/integrate...origin/upgrade/integrate` and no changed files.

**2. [auto] The environment.**
`uv sync --all-extras` (use `~/.local/bin/uv` if `uv` is not found).
You should see: it ends with `Audited N packages` or `Installed N packages`. Then `ls .venv/bin/zpkt .venv/bin/hands .venv/bin/ears .venv/bin/mlab` prints four paths.

**3. [auto] The preflight.**
`scripts/walkthrough_preflight.sh`
You should see: sections Checkout, uv environment, Ports, Supervisors, Live, Files, Other agents, Disk. Every uv
line is `ok`. It names the set in front and says whether it has unsaved changes. It ends with
`preflight: nothing needs attention`, or lists WARN lines. It changes nothing. (`--no-ui` skips reading Live's window.)

**4. [you] Decide about HW002_121_pp_finish's unsaved changes.** (Agent: never decide this. Ask Anthony, and wait.)
Only if the preflight says it is in front with unsaved changes. In Live, either press Cmd+S to keep them in the set,
or use File > Save Live Set As… with a new name such as `HW002_121_pp_finish_keep-<date>`. Save As leaves
`HW002_121_pp_finish.als` as it was last saved, and your changes go into the new file.
You should see: the preflight now says `unsaved changes: no`.

**5. [auto] Back up the desk's files that live outside git.**
```bash
B=~/_agent_scratch/walk/backup-$(date +%Y%m%d-%H%M); mkdir -p "$B"
cp -p ~/_agent_scratch/mixdesk/history/HW002_121_pp_finish.json "$B/"
cp -Rp ~/Music/zpkt/sets/state/HW002_121_pp_finish "$B/state"
cp -Rp ~/Music/zpkt/sets/surfaces/HW002_121_pp_finish "$B/surfaces"
cp -p ~/_agent_scratch/mixdesk/viz/analysis.json ~/_agent_scratch/arranger/arrangements/short-8d2a2.json "$B/"
cp -p "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/zpkt desk meter.amxd" "$B/"
ls "$B"
```
You should see: `HW002_121_pp_finish.json`, `analysis.json`, `short-8d2a2.json`, `state`, `surfaces`, `zpkt desk meter.amxd`.
Why: the desk keeps its history and checkpoints under HW002_121_pp_finish's name, whatever set is in front.

**6. [auto] Make the test copy.**
`cp -p ~/Music/zpkt/sets/HW002_121_pp_finish.als ~/Music/zpkt/sets/HW002_121_pp_walk.als`
You should see: the preflight lists `set HW002_121_pp_walk.als`. The copy holds what the set held when last saved.
Its name starts with `HW002_121_pp_`, so the rig's guards accept it.

**7. [auto] Stop the running mix desk, if it is the old one.**
Read the preflight's line for port 8985.
- It says `from /Users/…/Desktop/zpkt-main`: run `pkill -f 'zpkt-main/contrib/mixdesk/server.py'`.
- It says `from …/zpkt-upgrade`: the upgraded desk already runs. Stop it too for now:
  `pkill -f 'zpkt-upgrade/contrib/mixdesk/server.py'`. Part 7 starts it again.

You should see: `pgrep -fl mixdesk/server.py` prints nothing, and the preflight says `tcp 8985 mix desk: free`.

**8. [auto] Open the copy in Live.**
Only after step 4. `uv run zpkt live open HW002_121_pp_walk --no-save`
You should see: `opened HW002_121_pp_walk in N s`. If Live asks whether to save, stop: answer it yourself.

**9. [auto] Preflight again.**
`scripts/walkthrough_preflight.sh`
You should see: `set in front: HW002_121_pp_walk`, `unsaved changes: no`, `no dialog open in Live`.

## Part 2. zpkt live basics, on the copy

Run each from `~/Desktop/zpkt-upgrade`. Live shows HW002_121_pp_walk throughout.

**10. [auto] Ping.** `uv run zpkt live ping`
You should see: `pong in N ms`, N well under a second.

**11. [auto] The old name.** `uv run hands live ping`
You should see: the same line.

**12. [auto] The guard.** `uv run zpkt live check`
You should see: `HW002_121_pp_walk`, exit 0.

**13. [auto] Dialogs.** `uv run zpkt live modals`
You should see: `CLEAN`.

**14. [auto] Read a value.** `uv run zpkt live exec "result = song.tempo"`
You should see: `160.0`.

**15. [auto] Read a list.** `uv run zpkt live exec --json "result = [t.name for t in song.tracks][:6]"`
You should see: a JSON list of the first six track names.

**16. [auto] The agent's read-only rule.** `ZPKT_AGENT=1 uv run zpkt live exec "song.tempo = 120"`
You should see: an `ERROR:` line that says `hands live exec` only reads Live when the agent runs it, exit 1. Step 14
still prints `160.0`.

**17. [auto] `hands` from any folder.** `cd /tmp && ~/Desktop/zpkt-upgrade/hands/bin/hands --help; cd -`
You should see: the usage, listing `live`, `panel`, `song`, `rig`, `kit` and the rest.

**18. [auto] The skill's doctor.** `bash agent/skills/ableton-live-control/scripts/doctor.sh`
You should see: `[ok] Live process running` and `[ok] Path B MCP reachable (TCP 16619); LOM round-trip OK`, exit 0.

**19. [auto] The rig check, without playing.** `uv run zpkt live rig check --no-play`
You should see: `ready: Live answers, plays and has an audio device`, or a short list of problems. Do not run
`zpkt live rig reset` as a fix while HW002_121_pp_finish is in front.

**20. [auto] The Remote Scripts Live loads are this checkout's.**
```bash
for s in AbletonLiveMCP ZpktMiniLabTempo; do
  diff -rq -x __pycache__ -x '*.pyc' "src/zpkt/live/remote_scripts/$s" "$HOME/Music/Ableton/User Library/Remote Scripts/$s"
done
```
You should see: no output. If files differ, `make remote-script` copies them, and Live must restart to load them.
Do that only after step 4, and say so before anyone restarts Live.

## Part 3. Export and Save As

**21. [auto] Export by keystrokes (`zpkt live export`).**
`uv run zpkt live export walk-keys.wav --start 0 --length 16`
You should see: Live's Export dialog open and close. It prints `~/Music/zpkt/renders/walk-keys.wav` (in full).

**22. [auto] Check that file.**
`afinfo ~/Music/zpkt/renders/walk-keys.wav | grep duration` and `uv run zpkt audio measure ~/Music/zpkt/renders/walk-keys.wav`
You should see: `estimated duration: 6.000 sec` (16 beats at 160 BPM). The sheet shows an integrated loudness
that is a real number, not `-inf`.

**23. [auto] Export by the menu, and Save As, through the library.**
This is what the arranger, the mix desk and the booth now share (`zpkt.live.ops`, `zpkt.live.export`).
```bash
uv run python - <<'PY'
from pathlib import Path
from zpkt.live.export import SavePanel
from zpkt.live.ops import LiveOps
from zpkt.live.transport import LiveClient

home = Path.home()
ops = LiveOps(LiveClient(), staging=home / "_agent_scratch/arranger/raw", save_panel=SavePanel(reach="go_to_folder"))
print(ops.export(home / "Music/zpkt/renders/walk-menu.wav", 0, 16))
print(ops.save_as(home / "_agent_scratch/HW002", "HW002_121_pp_walk2", project=False))
PY
```
You should see: the Export dialog, then the Save panel, driven by menu clicks. It prints the render's path, then
`…/HW002_121_pp_walk2.als`. Live's title becomes `HW002_121_pp_walk2`. `afinfo` on the render says 6.000 sec.
If a macOS file-permission prompt appears, it freezes Live until you answer it: that is yours.

**24. [auto] Back to the copy.**
`uv run zpkt live open HW002_121_pp_walk`
You should see: `opened HW002_121_pp_walk in N s` (it saves HW002_121_pp_walk2 first, which is harmless).

**25. [auto] Save with a named copy.**
`uv run zpkt live save --as HW002_121_pp_walk3`
You should see: `saved …/HW002_121_pp_walk.als` or `nothing to save in …`, then `copy …/HW002_121_pp_walk3.als`.

**26. [auto] It refuses to overwrite.**
`uv run zpkt live save --as HW002_121_pp_walk3`
You should see: `…/HW002_121_pp_walk3.als exists; pick another name`, exit 1.

**27. [auto] A real-time take.**
`uv run zpkt live record --arrangement --beats 8 --output ~/Music/zpkt/renders/walk-rec.wav`
You should see: Live plays for about 5 s (out loud: 8 beats and a 4-beat tail). The WAV is kept whole, with the
pre-roll before beat 0, so `afinfo` says about 7 s; `walk-rec.wav.timing.json` beside it says where beat 0 is.

## Part 4. The whole mix as data: take, diff, put

**28. [auto] Take.** `uv run zpkt live state take walk-before`
You should see: `…/sets/state/HW002_121_pp_walk/walk-before.json  (N tracks, M values, about 3 s)`.

**29. [auto] Change one value.** `uv run zpkt live exec "song.return_tracks[0].mixer_device.volume.value = 0.5"`
You should see: `None`. The first return's fader moves in Live.

**30. [auto] Diff.** `uv run zpkt live state diff walk-before`
You should see: `M values in A, 1 differ` and one row for that return's volume, exit 1.

**31. [auto] Put.** `uv run zpkt live state put walk-before`
You should see: `put, Live matches`. The fader is back.

**32. [auto] Diff again.** `uv run zpkt live state diff walk-before`
You should see: `M values in A, 0 differ`, exit 0.

**33. [auto] List.** `uv run zpkt live state ls`
You should see: `walk-before` first.

**34. [auto] Two files, no Live.**
`uv run zpkt live state diff ~/Music/zpkt/sets/state/HW002_121_pp_walk/walk-before.json ~/_agent_scratch/arranger/arrangements/short-8d2a2.json`
You should see: `N values in A, K differ` and rows: what moved since the recipe's desk was written.

**35. [auto] Two saved sets, no Live.**
`uv run zpkt live als mix ~/Music/zpkt/sets/HW002_121_pp_walk3.als --against ~/Music/zpkt/sets/HW002_121_pp_walk.als`
You should see: `N values in A (HW002_121_pp_walk.als), 0 differ in B (HW002_121_pp_walk3.als)`, exit 0.

## Part 5. Panels and grids, and Zpkt web

Live must be stopped (not playing). Work in a scratch folder: `mkdir -p ~/_agent_scratch/walk && cd ~/_agent_scratch/walk`.
`H=~/Desktop/zpkt-upgrade/hands/bin/hands` saves typing.

**36. [auto] Parameters.** `$H panel params Operator --grep 'wave|filter'`
You should see: Operator's wave and filter parameters, with ranges and what Live shows.

**37. [auto] Make a panel.**
```bash
$H panel make --spec - > panel.out <<'JSON'
{"name": "walk-bass", "instrument": "Operator", "tempo": 104,
 "params": {"Osc-A Wave": "Saw D", "Filter Freq": "600 Hz", "Filter Res": "45 %"},
 "notes": [["A2", 0, 0.4, 115], ["C3", 1.5, 0.4, 105], ["E3", 3, 0.5, 110]], "beats": 8,
 "controls": [{"param": "Filter Freq", "label": "Cutoff"}, "Filter Res"]}
JSON
cat panel.out
```
You should see: a line `panel walk-bass v1`, a ```` ```audio ```` block and a ```` ```zpkt-surface ```` block. Live has a
new track `panel walk-bass` at the end. Tempo, loop and selection are as they were.

**38. [auto] Zpkt web's own parser reads it.**
```bash
node --input-type=module -e "import {readFileSync} from 'node:fs'; import {panelOutput} from '$HOME/zpkt-web/lib/panels.mjs'; const r = panelOutput(readFileSync('panel.out', 'utf8')); console.log(r ? r.facts : 'NOT PARSED')"
```
You should see: `panel walk-bass v1`, not `NOT PARSED`.

**39. [auto] A grid.** `$H panel grid walk-bass --axes '{"cutoff": {"from": "200 Hz", "to": "2 kHz", "steps": 4}}'`
You should see: a `grid …` line and one audio deck with versions A, B, C and D.

**40. [auto] Pick one.** `$H panel pick walk-bass 1 C`
You should see: `picked …`. Live's Filter Freq takes version C's value. Nothing renders again.

**41. [gui] In Zpkt web, with the upgraded `hands`.**
Zpkt web runs `~/.local/bin/hands`, which points at zpkt-main. To try the upgrade there:
`ln -sfn ~/Desktop/zpkt-upgrade/hands/bin/hands ~/.local/bin/hands`.
In Zpkt web on the phone, ask for a short saw bass with a cutoff knob.
You should see: a card with knobs and an A/B deck. It plays. Turning a knob and pressing Render gives the next
version. Afterwards put the link back: `ln -sfn ~/Desktop/zpkt-main/hands/bin/hands ~/.local/bin/hands`.

**42. [auto] Drop it.** `$H panel drop walk-bass` (and any panel step 41 made)
You should see: the `panel walk-bass` track is gone. The renders stay in `renders/`.

## Part 6. zpkt audio: measure and analyze

`F=~/_agent_scratch/mixdesk/renders/match.flac` (the 22 Nov reference-match render).

**43. [auto] Measure.** `uv run zpkt audio measure $F`
You should see: the full sheet: integrated loudness, true peak, LRA, PLR, spectra. No error.

**44. [auto] The old name gives the same numbers.** `uv run mlab measure $F`
You should see: the same sheet, number for number.

**45. [auto] Analyze with the embedding.** `uv run zpkt audio analyze $F`
You should see: the profile with an `Embedding` section, and no `DCLAP model not found`.

**46. [auto] The embedding's size.**
`uv run zpkt audio analyze $F --json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['embedding']))"`
You should see: `512`.

**47. [auto] Codecs through ffmpeg.** `uv run mlab deliver $F`
You should see: rows for `aac128` and `opus160`.

**48. [auto] An mp3 input.**
`ffmpeg -loglevel error -y -i $F -b:a 192k ~/_agent_scratch/walk/match.mp3 && uv run mlab measure ~/_agent_scratch/walk/match.mp3`
You should see: a sheet marked `lossy:mp3`.

**49. [auto] Against the references.**
`uv run zpkt audio target $F --refs ~/_agent_scratch/arranger/refs/refs.json --set hw002`
You should see: build and drop tables against the four references. The drop's rms distance is about 1.73 dB and the
build's about 2.17 dB, as on 22 Nov.

**50. [auto] The full calibration, with ffmpeg.**
`cd ~/Desktop/zpkt-upgrade/ears/mlab && uv run mlab calibrate; echo "exit $?"; cd -`
You should see: `exit 0` and every row passing in `ears/mlab/calibration/CALIBRATION.md`, the ffmpeg and pyloudnorm
cross-checks included. If `git diff` shows only its date changed, `git checkout -- ears/mlab/calibration/CALIBRATION.md`.

**51. [auto] The audio libraries contrib scripts use.**
`uv run --extra audio python -c "import numpy, scipy, soundfile, pyloudnorm, librosa; print('ok')"`
You should see: `ok`.

**52. [auto] The library inventory measures masters.** `uv run zpkt live library inventory --measure --json | head -c 800`
You should see: JSON in which a track with a master WAV has numbers for `lufs` and `true_peak`, not `null`. It can
take a few minutes (the library is in iCloud). No track has a master WAV yet, so also measure one file the way the
inventory does:
`uv run python -c "from pathlib import Path; from zpkt.live.library.inventory import measure_mlab; print(measure_mlab(Path.home() / '_agent_scratch/mixdesk/renders/match.flac'))"`
prints `lufs`, `true_peak` and `seconds` as numbers.

## Part 7. The mix desk

Live shows HW002_121_pp_walk. No desk runs (step 7).

**53. [auto] Start the upgraded desk.**
```bash
cd ~/Desktop/zpkt-upgrade && (nohup zsh -c 'while true; do ~/Desktop/zpkt-upgrade/.venv/bin/python ~/Desktop/zpkt-upgrade/contrib/mixdesk/server.py; sleep 2; done' >> ~/_agent_scratch/mixdesk-server.log 2>&1 &)
sleep 8; tail -5 ~/_agent_scratch/mixdesk-server.log
```
You should see: `mix desk on http://127.0.0.1:8985`. The preflight shows 8985, 8986 and 8987 held from zpkt-upgrade.
If the copy lacks monitor tracks, the log lists them being added (`mon A`, `mon B`, `mon C1`–`mon C4`).

**54. [auto] Load the upgraded pager into Live.**
`curl -s -X POST http://127.0.0.1:8985/api/restart`, then
`curl -s http://127.0.0.1:8985/api/state | python3 -c "import json,sys; print(json.load(sys.stdin)['live'])"`
You should see: `{"ok": true}`, then `attached`.

**55. [auto] Monitor tracks.** `.venv/bin/python contrib/mixdesk/monitor.py status`
You should see: JSON naming `mon A`, `mon B` and `mon C1` to `mon C4`.

**56. [auto] The page.** Open http://127.0.0.1:8985/ on the Mac (on the phone: `https://<your-mac>.ts.net:8985/`).
You should see: on the left one MiniLab page of tiles (slot, dial or fader, a large value, the name). On the right
A / B / W / C, Play, the loop and the waveform. No scrollbar. The status has a green dot and says `MiniLab 3 → Live`. Press `?`: the keys list.

**57. [you] Pages from the MiniLab.**
Press pads 1 to 8 in turn. Then press pad 1 twice. Then turn the big encoder. Pad bank A or B does not matter: both
arm pages.
You should see: each pad arms its page on the screen (Buses, Kick, Hats, Break, Chord + perc, Transitions, Space,
Main). Pad 1 twice shows A1·2, Match A/B. The encoder steps through the pages.

**58. [you] Fader pickup.**
On Buses, move fader 1 slowly from the bottom up.
You should see: nothing moves in Live until the fader passes Live's value. Until then the page draws a blue line
where the fader is. After that the fader drives the kick bus.

**59. [you] Knobs and switches.**
Turn K1. Click a switch tile on the page.
You should see: Live and the tile move together, and the value eases. The click flips the switch in Live and on the tile.

**60. [gui] Monitor A / B / W / C.** (Agent: switch, check the state and the level match. Anthony: listen.)
Press Play (or space). Switch A, B, W, C (keys A B W C; 1–4 pick the reference while C plays).
You should see and hear: A is the original render, B the recipe's render, W the working mix live, C the chosen
reference from the drop. The switches are level-matched: no jump in loudness. On W, a knob changes what you hear.

**61. [gui] History and undo.**
Turn a knob, wait 3 s, turn it again. Press Z, then Shift+Z.
You should see: two steps in the bar under the tabs. Z puts Live back one step, Shift+Z redoes it.
`curl -s http://127.0.0.1:8985/api/history | python3 -m json.tool | tail -20` shows the steps.

**62. [auto] A checkpoint.** `curl -s -X POST -d '{"name": "walk-1"}' http://127.0.0.1:8985/api/checkpoint`
You should see: `{"ok": true, "name": "walk-1"}` and `~/Music/zpkt/sets/state/HW002_121_pp_finish/walk-1.json` exists.

**63. [gui] Compare and revert.**
Move two knobs. Under Changes, compare from `walk-1` to now. Try Highlight, then Only changed. Press revert on one
control, then Revert these.
You should see: the moved controls lit, with what they were; the page tabs count them. Revert puts each back as one
undoable step. Whole mix first saves a `before-revert-…` checkpoint, then puts everything back.

**64. [gui] Make a surface.**
Claude must be signed in on the Mac (`claude`, then `/login`). Go to the last page, ＋ Make a surface. Type
"kick drive and hats air on two knobs" and press Make surface.
You should see: within a minute a new page, armed on the MiniLab. Its tiles name real controls; anything not in the
set is listed as dropped. Its file in `~/Music/zpkt/sets/surfaces/HW002_121_pp_finish/` has `"schema": 1`. A macro
knob moves its parameters together. Press Remove: the file moves to `removed/`.

**65. [gui] The live meter.**
If Main has no "zpkt desk meter", run `.venv/bin/python contrib/mixdesk/meter.py install` (step 5 kept a copy of the
preset). Play, on W.
You should see: the blue spectrum curve moves with the music and sits on the renders' scale.

**66. [auto] Stop the upgraded desk for the scripts.**
`pkill -f 'zpkt-upgrade/contrib/mixdesk/server.py'`
You should see: `pgrep -fl mixdesk/server.py` prints nothing.

**67. [auto] The meter's datagrams.**
`uv run zpkt live exec "song.start_playing()"`, then `.venv/bin/python contrib/mixdesk/meter.py listen`, then
`uv run zpkt live exec "song.stop_playing()"`
You should see: `31 bands [...] ...`.

**68. [auto] The recipe, offline.** `.venv/bin/python contrib/mixdesk/recipe.py show`
You should see: `desk from HW002_121_pp_finish, written <date>`, the two returns, the monitor tracks and one line
per desk device and mixer.

**69. [auto] The recipe onto the copy.** `uv run python contrib/mixdesk/recipe.py apply --set HW002_121_pp_walk`
You should see: `recipe applied`. The copy now holds the 22 Nov recipe's desk.

**70. [auto] The source analysis.** `.venv/bin/python contrib/mixdesk/analyze.py`
Then `cmp ~/_agent_scratch/mixdesk/viz/analysis.json ~/_agent_scratch/walk/backup-*/analysis.json`
You should see: no output from `cmp`: the same sources give the same file. If it differs, keep both and ask an
agent to compare the numbers.

**71. [you] Optional, on the real finishing set: one render each way.**
Only if you saved HW002_121_pp_finish yourself in step 4. Open it yourself in Live (File > Open Recent). Then:
```bash
cd ~/Desktop/zpkt-main && uv run --project hands python contrib/mixdesk/match.py render main-check
cd ~/Desktop/zpkt-upgrade && uv run python contrib/mixdesk/match.py render upgrade-check
uv run python contrib/mixdesk/match.py snapshot upgrade-check
uv run mlab measure ~/_agent_scratch/mixdesk/renders/main-check.flac
uv run mlab measure ~/_agent_scratch/mixdesk/renders/upgrade-check.flac
```
You should see: each render takes about 16 s in Live and changes no mix value. The two sheets agree: integrated
loudness within 0.1 LU, true peak within 0.1 dB. The snapshot prints its file in `~/_agent_scratch/mixdesk/snapshots/`.
Then open HW002_121_pp_walk again yourself (File > Open Recent). If Live asks to save the finishing set, choose
Don't Save: the renders only moved the selection.

**72. [auto] The workspace script's Save As, and its guard.**
Live shows HW002_121_pp_walk. Open the arranger's mix set: `uv run zpkt live open HW002_121_pp_mix` (it saves the
copy first, which is harmless). Then `uv run python contrib/mixdesk/workspace.py save`.
You should see: `snapshot: …/HW002_121_pp_mix_unsaved_<today>.als` (a Save As through the GUI), then
`STOP: …/HW002_121_pp_finish.als exists`. The finishing set is never overwritten. If a snapshot for today already
exists, only the STOP line appears.

## Part 8. The arranger

No desk runs. The walkthrough runs the arranger on port 8976 with its own copy of the saved arrangements, so the
phone's arranger state stays as it is.

**73. [auto] A data folder for the check.**
```bash
W=~/_agent_scratch/arranger-walk; mkdir -p "$W"
for f in ~/_agent_scratch/arranger/*; do ln -s "$f" "$W/"; done
rm "$W/arrangements" "$W/mix2" "$W/spectral" "$W/transitions.json"      # removes only these links
cp -Rp ~/_agent_scratch/arranger/{arrangements,mix2,spectral,transitions.json} "$W/"
ls -l "$W"
```
You should see: links for `audio`, `raw`, `refs` and the rest, and real folders for `arrangements`, `mix2`, `spectral`.

**74. [auto] Start it.** In its own terminal tab:
```bash
cd ~/Desktop/zpkt-upgrade/contrib/arranger
ARRANGER_DATA=$HOME/_agent_scratch/arranger-walk ARRANGER_PORT=8976 ~/Desktop/zpkt-upgrade/.venv/bin/python server.py
```
You should see: `arranger on http://127.0.0.1:8976 (data /Users/…/arranger-walk)`. Use the repo's Python: macOS's
`/usr/bin/python3` (3.9) can no longer run it. For the phone: `tailscale serve --bg --https=8976 http://127.0.0.1:8976`
(and `tailscale serve --https=8976 off` afterwards).

**75. [auto] Its API.** `curl -s http://127.0.0.1:8976/api/arrangements | head -c 300`
You should see: a JSON list that includes `short-8d2a2`.

**76. [gui] Every page plays.** (Agent: each loads and its playback moves on the bar. Anthony: listen.)
Open `/`, `/transitions/`, `/mix/`, `/mix2/`, `/spectral/`, `/kick/` on the phone.
You should hear and see: each loads and plays rendered files, in time on the bar. The transitions faders and the
mix-1 gain, pan and cuts work. Nothing else makes sound.

**77. [gui] Save from the arrangement page.**
On `/`, mute one region and save. On `/transitions/`, move one fader. On `/mix/`, set one card's level.

**78. [auto] The save kept the desk.**
```bash
python3 - <<'PY'
import json, pathlib
home = pathlib.Path.home()
walk = json.loads((home / "_agent_scratch/arranger-walk/arrangements/short-8d2a2.json").read_text())
real = json.loads((home / "_agent_scratch/arranger/arrangements/short-8d2a2.json").read_text())
print(sorted(walk))
print("desk kept:", walk.get("desk") == real.get("desk"), "| saved:", walk.get("saved"))
PY
```
You should see: the keys include `desk`, `mix`, `mix2`, `regions`, `transitions`; `desk kept: True`; a new `saved` stamp.

**79. [gui] One mix-2 batch.**
Live shows `HW002_121_pp_mix` (step 72 left `…_unsaved_<today>` in front: `uv run zpkt live open HW002_121_pp_mix` saves
that snapshot and opens the mix set). On `/mix2/`, queue a batch of two points (one channel, Saturator, Drive, 2
steps, 4 bars).
You should see: the page shows the batch queued, then rendering, then ready. Its renders play and switch on the bar.

**80. [auto] Where the queue stands.** `curl -s http://127.0.0.1:8976/api/mix2/queue` while it renders, then after.
You should see: first `"worker": "running"` with the batch under `rendering`; at the end `"worker": "idle"` and
`counts` with `ready: 1`. The worker's log is `~/_agent_scratch/arranger-walk/mix2/worker.log`.

**81. [auto] The spectral "before" render, into the copy.**
`cd ~/Desktop/zpkt-upgrade && ARRANGER_DATA=$HOME/_agent_scratch/arranger-walk uv run python contrib/arranger/spectral.py before`
Then measure both: `uv run mlab measure ~/_agent_scratch/arranger-walk/spectral/before.flac` and the same for
`~/_agent_scratch/arranger/spectral/before.flac`.
You should see: the same length, and loudness within 0.1 LU, unless a mix-2 point was kept since the old render.

**82. [auto] One bounce.**
Open the loops set: `uv run zpkt live open HW002_121_pp_loops --no-save`. Live will ask whether to save the mix set,
which the worker changed: choose Don't Save yourself. Then:
```bash
mv ~/_agent_scratch/arranger/raw/stems/splash.wav ~/_agent_scratch/arranger/raw/stems/splash.before-walk.wav
uv run python contrib/arranger/bounce.py splash
afinfo ~/_agent_scratch/arranger/raw/stems/splash.wav | grep duration
afinfo ~/_agent_scratch/arranger/raw/stems/splash.before-walk.wav | grep duration
```
You should see: one Main export with the splash soloed, a few minutes. Both files have the same duration, and
`uv run mlab measure` on each gives the same loudness within 0.1 LU. Keep the new one, or move the old one back.

**83. [auto] Stop the arranger.** Ctrl-C in its tab.
You should see: the preflight says 8976 is free. The data folder can stay or go.

## Part 9. The harness

The running harness (8787, from `~/Desktop/zpkt`) keeps serving. The check runs the upgraded one on 8877, with its
own password file and studio folder.

**84. [auto] Start it.** In its own terminal tab:
```bash
cd ~/Desktop/zpkt-upgrade/contrib/harness
HARNESS_WEB_PORT=8877 HARNESS_SKRNG=$HOME/_agent_scratch/walk/skrng HARNESS_STUDIO=$HOME/_agent_scratch/walk/studio uv run harness serve
```
You should see: it keeps running, and the preflight shows 8877 held from zpkt-upgrade. For the phone:
`tailscale serve --bg --https=8877 http://127.0.0.1:8877` (`… --https=8877 off` afterwards).

**85. [auto] The gate.**
`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8877/studio/api/artist/repertoire` and
`curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:8877/studio/lab/`
You should see: `401`, then `302 http://127.0.0.1:8877/login?next=…`.

**86. [gui] First visit and the home page.**
Open http://127.0.0.1:8877/. Set a password (it is only for this check's folder).
You should see: `/studio/`, a home page linking Gemini, the lab and /skrng. No chat, no jobs.

**87. [gui] /skrng through the proxy.** Follow the /skrng link.
You should see: the site's /skrng pages, for listening only (no feedback buttons).

**88. [gui] The lab.** Open `/studio/lab/`.
You should see: HW002's controls as surfaces, and the arrange surface's bars. Do not press its pads: the lab still
carries its old browser sound, which `contrib/docs/sound.md` lists as breaking the rule and waiting to be replaced.

**89. [gui] Gemini sessions.**
Open `/studio/gemini/` (on the phone through the tailnet link). Start a session and write "hello". Then ask it to run
`touch ~/_agent_scratch/walk/gemini-permission-check.txt`.
You should see: a streamed answer to hello. For the `touch` a permission request; an ntfy notification reaches the
phone; after your yes, the file exists. The page shows the session's cost. It costs a few cents. (Gemini CLI runs
commands that only read, such as `git status`, without asking.)

**90. [auto] Gemini CLI.** `uv run harness gemini -p "say hello in five words"`
You should see: a five-word answer from Gemini CLI.

**91. [auto] The artist.** `uv run harness artist show`, then `uv run harness artist propose --dry-run`
You should see: the repertoire, plates and last presses; then Claude's proposed notes and works, with nothing kept.

**92. [auto] The lab's parameters.** `uv run harness lab-params; git -C ~/Desktop/zpkt-upgrade diff --stat`
You should see: `100 parameters -> …/static/lab/data/params.json` and no diff (or only values you changed in the set
since). Undo an unwanted diff with `git checkout -- contrib/harness`.

**93. [auto] Stop it.** Ctrl-C in its tab.

## Part 10. The checklist prototype

**94. [auto] Start it.** In its own tab: `cd ~/Desktop/zpkt-upgrade/prototypes/checklist && uv run python server.py`
You should see: it serves http://127.0.0.1:8798/studio/checklist/ on loopback, with no password.

**95. [auto] The harness routes it mounts.** `curl -s http://127.0.0.1:8798/studio/api/artist/repertoire | head -c 200`
You should see: JSON, not a login page.

**96. [gui] The pages.**
Open `/studio/checklist/`, then `map/`, `rummage/`, `wasteland/`, `flow/`, and `concepts/crystal.html`,
`concepts/repair.html` and `concepts/stamps.html` (`concepts/` has no page of its own).
You should see: each loads. On the map, a stamp plays its check sound.

**97. [gui] The artist's quick question.** (Agent: run it with `--no-model` and a temporary data folder, so no real feedback is kept.)
On the map, press a thumb. (It is kept as real feedback in the artist's data.)
You should see: a short question that names what was on screen. With `--no-model` it comes from rules instead.
Stop the server with Ctrl-C afterwards.

## Part 11. The image wall (its own repo)

**98. [auto] List.** `cd ~/Desktop/image-wall && uv run images list | tail -5`
You should see: the latest images, with batch and title.

**99. [gui] The wall.** (Agent: check a thumb works against a copy of the votes file, not the real one.) In its own tab: `uv run images serve`. Open http://127.0.0.1:8796/. Press a thumb on one image.
You should see: every image with its context and prompt. `tail -1 ~/_agent_scratch/studio/images/votes.jsonl` shows
your vote. Stop it with Ctrl-C.

**100. [gui] Optional, costs one image.**
`uv run images gen "a brass lamp on a desk" --context "walkthrough check" --batch walk-check`
You should see: the file's path, and the image on the wall.

## Part 12. The repos that moved out

These run from their own checkouts. Both take zpkt from `~/Desktop/zpkt-upgrade` for now.

### music-bot (`~/Desktop/music-bot`)

**101. [auto] Its tests.** `cd ~/Desktop/music-bot && make test`
You should see: booth 86 passed, bot 27 of 27.

**102. [auto] The booth without Live.**
`cd booth && uv run booth check palettes/examples/clockwork.json && uv run booth plan palettes/examples/clockwork.json`
You should see: `ok` with an estimate, then the tracks, note counts and mixer. While the booth's home is a link to
the offload disk that is not there, both stop with `FileExistsError`: put `BOOTH_HOME=~/_agent_scratch/walk/booth-home`
before each.

**103. [gui] One watched booth export.**
The booth's home, `~/_agent_scratch/booth`, is a link to the offload disk and is not there now. Restore it first.
Then, with no booth serving (8794 free) and `booth_template` in front of Live:
`uv run booth status`, `uv run booth close "watched run"` (only if nothing runs or waits),
`uv run booth run palettes/examples/clockwork.json`, `uv run booth open`.
You should see: JSON with `"state": "done"`, files including `video.mp4`, and `measure.lufs` near -14. The export
goes through the moved Save As and export code.

Moving the installed bot to this repo (`sudo bot/setup-mac.sh --update`) is a deploy step, not part of this check.

### zpkt-demo (`~/Desktop/zpkt-demo`)

**104. [auto] Its tests.** `cd ~/Desktop/zpkt-demo && uv run pytest -q -p no:cacheprovider`
You should see: all pass (livectl against a stand-in Live).

**105. [auto] livectl reads Live.** `uv run python tools/livectl.py x "song.tempo"`
You should see: the front set's tempo. Never run `livectl.py open` while HW002_121_pp_finish is in front: it saves
the set in front.

## Part 13. Put things back

**106. [auto] Restore the desk's history, and set aside the walkthrough's checkpoints.**
```bash
B=$(ls -d ~/_agent_scratch/walk/backup-* | tail -1)
cp -p "$B/HW002_121_pp_finish.json" ~/_agent_scratch/mixdesk/history/
diff -rq "$B/state" ~/Music/zpkt/sets/state/HW002_121_pp_finish
```
You should see: `diff` lists only files the walkthrough added (`start-…`, `walk-1`, `before-revert-…`). Move them into
`~/_agent_scratch/walk/` if you do not want them.

**107. [gui] Open the finishing set and choose the desk.** (Agent: keep the desk Anthony last chose; ask if unsure.)
Open HW002_121_pp_finish in Live yourself. Start one desk from the table at the top: zpkt-main's to go back, or
zpkt-upgrade's to keep the upgrade. Then `curl -s -X POST http://127.0.0.1:8985/api/restart`.
You should see: the page at :8985 says attached, and the MiniLab drives the finishing set again.

**108. [auto] Final preflight.** `scripts/walkthrough_preflight.sh`
You should see: the desk on 8985 from the checkout you chose, 8976, 8877, 8798 and 8796 free, and `~/.local/bin/hands`
pointing where you want it.

---

## Checklist

The agent fills this first, with a note per failure. Then Anthony does the [you] rows: 4 if it comes up,
57–59 at the MiniLab, the listening parts of 60 and 76, and 71 if he wants it.

| Step | What | Pass / fail |
|---|---|---|
| 1–9 | Setup, copy, preflight | Pass, but **step 8 is a coverage failure (permissions)**. `zpkt live open --no-save` timed out on Live's save dialog, and `rig reset --discard` left Live on "recover your work?". The rig's keys did not reach that dialog, and a direct keystroke was refused. It cleared only once Anthony let the agent use Live's window. Step 4: Anthony chose discard. |
| 10–20 | zpkt live basics | Pass after ba5d11e (`zpkt live ping` and the other live-group commands did not exist). 20: the installed ZpktMiniLabTempo differs from the repo only in formatting and one comment |
| 21–27 | Export, Save As, record | Pass. 27 keeps the take whole (7.5 s with pre-roll and tail): wording fixed |
| 28–35 | State take, diff, put; als mix | Pass |
| 36–42 | Panels, grid, pick; Zpkt web | 36–40 and 42 pass. **41 is a coverage failure (requests)**. http://127.0.0.1:8789/ answers 403 (Tailscale login only). On the tailnet URL the in-app browser blocks every API request, so the agent could not ask. Moved to Anthony (phone) |
| 43–52 | zpkt audio: measure, analyze, deliver, target, calibrate, inventory | Pass. `measure` writes its sheet into ears/mlab/reports in the checkout (removed each time) |
| 53–56 | Desk starts from the upgrade, pager attached, page | Pass. The status reads `MiniLab 3 → Live` with a green dot (wording fixed) |
| 57–59 | MiniLab: pages, pickup, knobs, switches | Anthony |
| 60 | Monitor A / B / W / C (agent switches; Anthony listens) | Agent part pass: each slot solos its own monitor track, C seeks to the drop, W clears all solos, level-match gains are set. Listening: Anthony |
| 61–63 | History, undo, checkpoints, revert | Pass, with the moves made in Live (the page has no knob input). Desk checkpoints are always filed under HW002_121_pp_finish, even on the copy; moves made by scripts are stamped `you` |
| 64 | Make a surface | Pass: made in 11 s, schema 1, real controls, armed, removed. Turning its macro knob is Anthony's (MiniLab) |
| 65, 67 | Live meter | Pass (31 bands while playing). Whether the curve sits on the renders' scale was not checked by eye |
| 68–70 | Recipe show and apply, analyze | Pass (apply 54 s; analysis.json byte-identical) |
| 71 | Render each way on the finishing set (optional) | Anthony, if he wants |
| 72 | Workspace Save As and its guard | Pass; the finishing set was untouched |
| 73–78 | Arranger pages; a save keeps the desk | Pass. 76 listening: Anthony |
| 79–80 | Mix-2 batch and the queue route | Pass on the second try. The first batch failed with silent renders because **HW002_121_pp_mix.als (saved 18 Nov) has its six buses' monitoring Off and its tempo at 124**. `mixset.py build` sets both, but the worker never checks them. That predates the upgrade. The buses were set to In for this run only, without saving |
| 81 | Spectral before | Pass at 160 BPM: 60.00 s both, −16.78 against −16.81 LUFS. At the saved 124 BPM it was 77.4 s |
| 82 | One bounce | Pass: 270 s both. Loudness −26.18 against −26.06 LUFS, but the splash chain is not deterministic (two new bounces differ as much as new against old) and the loops set changed after the old stem. Old stem put back |
| 84–88 | Harness: gate, home, /skrng, lab | Pass. The lab still has its old browser sound (known, sound.md) |
| 89–92 | Gemini sessions and CLI, artist, lab-params | Pass ($0.05). Gemini runs `git status` without asking (its own rule). ntfy: Anthony to confirm the phone got it |
| 94–97 | Checklist prototype | Pass (temp data, --no-model). `concepts/` has no index, as before the upgrade |
| 98–100 | Image wall | Pass (thumb on a copy; one image, batch walk-check) |
| 101–103 | music-bot: tests, booth check, watched export | 101–102 pass with BOOTH_HOME set (`booth check` crashes on the dangling ~/_agent_scratch/booth link). 103 not run: booth home is on the unplugged offload disk |
| 104–105 | zpkt-demo: tests, livectl | Pass |
| 106–108 | Put things back | Pass: history restored, walkthrough checkpoints moved to ~/_agent_scratch/walk, finishing set in front with no unsaved changes, the upgraded desk attached on 8985, hands link on zpkt-main |
