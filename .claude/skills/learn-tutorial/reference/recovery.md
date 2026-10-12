# Recovery

Every Live incident a run has met, with how to detect it and how to fix it. Section names are the incident
kinds that `preflight.py` points to. `runlog.py incident` accepts them, plus `other` for anything new; a new
kind that recurs gets its own section here. `S` is the skill's scripts folder, and every command runs
through its launcher.

The rules hold through every fix:

- **One checked step at a time.** Check before each step, read back after it, and never chain past a
  surprise.
- **Keep LOM calls well under 12 s.**
- **Never discard or overwrite a set you don't own.**
- **Read each dialog from a screenshot,** then press its non-destructive button.

The practice agent stops and reports. Restarting Live and choosing what happens to someone else's set are
the orchestrator's calls. When the choice is Anthony's (his set, his prompts), ask him.

## dirty-set

The front set has unsaved changes.

- **Detect.** Two read-only signals that agree:
  - File > Save Live Set is enabled;
  - the front window's close button reports `AXEdited = true`.

  Both are checked by `preflight.py` and `live_step.py edited`. `song.can_undo` does not work, because
  loop-brace changes skip the undo history.
- **Why it matters.** Opening or creating another set raises "Save changes?". Meanwhile LOM keeps acting
  on the old set.
- **Run 1.** A `hands plan` render on the HW002 probe set set the loop brace and never saved, so the
  practice stopped at preflight.
- **Fix, if not ours.** Stop and report. The orchestrator decides. Run 1's fix, approved for an agent-owned
  probe set:
  1. back up the `.als` (`cp`, then `shasum` both copies);
  2. restore what the render changed;
  3. save it through the File menu;
  4. read back that it is clean (`$S/run live_step.py edited`).

  On a set Anthony works in, ask him.
- **Fix, if ours.** Run `$S/run live_step.py --log W/practice/live_steps.jsonl save --expect SET --path ALS`.
- **Never.** Press Don't Save on a set that is not ours, or `open` another set over a dirty one.
- **Hands gap:** `session.is_dirty`, and plan renders leaving their set dirty (TODO.md).

## audio-stall

Live's audio engine has stalled.

- **Detect.**
  - Log.txt shows `Internal Error: From 5 to Audio queue timeout` every ~3 s. `preflight.py` scans the last
    15 minutes.
  - A LOM read takes over 1.5 s, or a harmless write over 3 s. Run 1 saw 6.8 s against 0.9 s.
  - A set took 73.5 s to open.
  - The transport would not start, and a save hung behind an unnamed dialog.
- **Run 1.** This came after 5 days of uptime, with the audio device still selected and the audio engine on.
- **Fix (orchestrator).** Restart Live:
  1. save `SET` if it is in front (`live_step.py save`);
  2. press Don't Save only on throwaway Untitled sets;
  3. quit Live;
  4. relaunch it with `open -a "Ableton Live 12 Suite"`. It comes up on Untitled in about 6 s.

  Use `hands.live.session.restart` only when the front set is clean, or is `SET` already saved. It saves
  whatever set from `sets_dir` is in front, dirty or not, which would overwrite a set we don't own. If a
  set that is not ours is dirty, stop and ask.
- **Re-check after the restart.** Run `$S/run preflight.py --stage practice`. Once the run's own set is in
  front again, run
  `$S/run preflight.py --stage practice --ours SET --write-test --clock-test`. Without `--ours` the two
  tests are skipped.
- **If the clock still does not move:** check Live > Settings > Audio (the output device is selected) and
  Options > Audio Engine On.
- **Hands gap:** an audio-health preflight that does not play (TODO.md).

## old-template

A set from an older Live cannot be saved in place.

- **Detect.** Saving shows an alert saying the set was made by an older Live and must be saved as a new
  file, with the buttons [Cancel] [Save As…]. Its accessibility elements carry no text, so read it from a
  screenshot.
- **Run 1.** The practice started from Live's built-in `DefaultLiveSet.als` (made by Live 12.1).
- **Fix.**
  1. Press Cancel.
  2. Start from File > New Live Set (`live_step.py new`): an Untitled, Live-native set.
  3. Give it a name and folder at once with `live_step.py save-as`.
- **Hands gap:** `new_set` and `save_as` (TODO.md).

## foreign-prompt

A system prompt holds the key focus.

- **Detect.** `preflight.py` lists system prompts and the front app. Prompts come from
  UserNotificationCenter, CoreServicesUIAgent or SecurityAgent, for example "Allow ... to find devices on
  local networks?" or "... is an app downloaded from the Internet".
- **Run 1.** Keystrokes meant for Live went nowhere:
  - Cmd+Shift+R did not open the Export dialog;
  - the Save panel's Go-to-folder typing failed;
  - the file landed in Live's last-used folder.
- **Fix.**
  - Leave the prompt for Anthony; it is his to answer. Tell the orchestrator.
  - **What needs no keys:** LOM steps and `live_step.py save`, which presses the menu item.
  - **What still types:** `live_step.py save-as` (Go-to-folder) and `render.py` (Go-to-folder, Return,
    Escape). Both refuse while a prompt is open or Live is not the front app, because Return or Escape could
    answer the prompt. Wait until Anthony has answered it.
  - Export into the folder the Save panel already uses (`export-folder`).
- **Hands gap:** export by menu or AX press, with a read-back of the Save panel's folder (TODO.md).

## export-folder

The export landed somewhere other than the path asked for.

- **Detect.** `render.export` times out waiting for the file, yet Live shows no dialog.
- **Cause.** Go-to-folder typing failed (`foreign-prompt`), so Live used its last-used folder.
- **Fix.**
  1. Find the newest WAV in that folder (`ls -t`). It is usually the previous export's folder.
  2. Move it into `renders/`.
  3. From then on, export into that same folder.
- **Never.** Export over an existing file: Live trashes the old one and renames the new one.

## unnamed-dialog

Live's own alerts have no name or text that accessibility can read.

- **Detect.** `preflight.py` and `live_step.py` report an `AXDialog` whose name is empty.
  `$S/run --hands live modals` (reap_modals) skips such dialogs.
- **Fix.**
  1. Take a screenshot of Live's window first, and read the dialog.
  2. Run `$S/run live_step.py dialog`. It lists each button's index, position and size; match them to the
     screenshot.
  3. Press the non-destructive button (Cancel, or Don't Save on a throwaway) with
     `$S/run live_step.py --log W/practice/live_steps.jsonl press --index N --expect-pos X,Y`. It refuses if
     the button moved, or if it is titled Save, Replace or Delete.
  4. Record the text in the step log.
- **Never.** Press anything you have not read.
- **Hands gap:** `reap_modals` should report an unnamed dialog with its size and element count (TODO.md).

## dialog

A named dialog was left open: the Export dialog or a Save panel.

- **Fix.**
  1. Run `$S/run --hands live modals` to see it.
  2. If the dialog is from this run's own interrupted export, `hands.live.ui.close_dialogs()` cancels the
     Save panel and the Export dialog. Otherwise read it from a screenshot first.

## orphaned-osascript

An `osascript` from an earlier export is still running and holds the dialog.

- **Detect.** `preflight.py` lists any `osascript` running for more than 60 s.
- **Run 1.** An outer `perl alarm` around an export killed Python and left `osascript export_audio...`
  running.
- **Fix.** If its command line shows it is this run's own export script, kill that pid, then clear the
  dialogs (`dialog`). If it belongs to someone else, leave it and report.
- **Never.** Wrap an export in an outer timeout. `hands.live.ui.osa_file` has its own 900 s timeout. The
  Bash tool's own timeout counts as an outer one: run `render.py` in the background or with a 600000 ms
  timeout.

## device-self-noise

A device makes sound with no input.

- **Run 1.** Vinyl Distortion crackled through the lead-in and every bar, even with no clips on its track.
  The LOM cannot write arrangement automation, so the device could not be switched on for later bars only.
- **Fix.**
  1. Probe any noise, crackle or LFO-driven device with a short export that includes the lead-in.
  2. If it sounds by itself, render its output once (a track-mode export) into an audio clip.
  3. Put the clip on its own track, only where the plan wants it.
- **Hands gap:** arrangement automation for such devices (TODO.md).

## live-down

Live is not running, or the Remote Script does not answer.

- **Fix (orchestrator).**
  1. Run `lib/rig/start_headless.sh`.
  2. Check with `$S/run --hands live ping`.
  3. Re-run preflight.

## restart

Live's memory is high (over 5 GB).

- A fresh Live uses about 1.5 GB, against 4.5 GB after many loads.
- Restart between stages as in `audio-stall`. Do not restart in the middle of a build.

## disk

The disk is low.

- The scrape needs about 15 MB per 2.5 minutes of 720p video. Renders take about 11 MB per 30 s of 32-bit
  stereo.
- After the verdict, the retro may delete `src/*.mp4` (it can be fetched again) and `renders/superseded/`.

## selftest

The self-test failed.

- Do not let an onset or grid measurement decide anything.
- `selftest.py` prints the failing kind and sample rate. Fix the detector in `scripts/common.py` and make
  the self-test pass before the run continues.
- Record the change in LESSONS.md.
