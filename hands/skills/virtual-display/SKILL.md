---
name: virtual-display
description: Run, position, and screenshot native macOS GUI apps on a software virtual display so headless/off-screen GUI testing works without taking over the user's visible screen. Use for GUI testing, capturing app windows, or driving a Mac app that should not appear on the physical display. Requires Apple Silicon/Intel macOS, Homebrew, and BetterDisplay.
---

# Virtual Display for Headless macOS GUI Testing

macOS has no `Xvfb` for native (Cocoa/AppKit/SwiftUI) apps — they need a real
WindowServer session and a display. This skill adds an extra **software virtual
display** (via BetterDisplay) to the current login session and keeps all test
windows inside its coordinate region, which the physical screen does not render.
Result: you can launch, position, interact with, and screenshot GUI apps entirely
off-screen.

## Polite interaction with the human user

`run-on-vdisplay.sh` and `capture.sh` source `scripts/_polite.sh`, which:

- **Tracks presence** via system-wide keyboard/pointer idle time (`ioreg`
  `HIDIdleTime`). The user counts as "around" if seen in the last 10 minutes
  (`PRESENCE_WINDOW_SECS`, default 600).
- **Asks before taking control or screenshotting** when the user is around:
  shows a dialog with a 10-second countdown (`COUNTDOWN_SECS`), then proceeds
  automatically — it does not block indefinitely waiting for a click.
- **Leaves a sticky note** (via Stickies.app) recording what it did and when,
  whenever it takes over the screen while the user was away.

All screen-capture defaults to the **virtual** display (`-D 2`), not the real
one (`-D 1`). Override with `DISPLAY_ID=1` if you deliberately need the real
screen. The helper scripts live in `scripts/`; reference them by their absolute
path when running (they are outside the current project).

## Cursor takeover: return is enforced, not remembered

Any time you move the physical pointer (`cliclick`, GUI-automation clicks) you
have taken over the user's cursor, and it MUST end back at the center of their
primary physical display. This is enforced deterministically, so you do not rely
on remembering it:

- **Any ad-hoc pointer command runs through the wrapper**, which parks the cursor
  on every exit path (success, failure, or interrupt) and preserves the wrapped
  command's exit code:

  ```sh
  bash scripts/with-cursor-parked.sh cliclick c:1200,680 c:1185,711
  ```

  Never run a raw `cliclick` (or a one-off GUI-automation `osascript` that
  clicks) directly -- wrap it, so the pointer is guaranteed to come back.

- **Sanctioned takeover scripts self-park** via an `EXIT` trap, so they return
  the cursor even if they error out; you do not wrap those again.

- `scripts/park-cursor.sh` is the primitive both of the above call. It reads the
  main display (the one with the menu bar) via CoreGraphics and moves the cursor
  to its center. Run it directly only if you need a bare park.

Note: `create.sh`, `run-on-vdisplay.sh`, and `capture.sh` position windows via
System Events and screenshot via `screencapture` -- they do not move the pointer,
so they need no parking. Pointer movement here comes only from `cliclick`.

## Prerequisites (check first)

1. **BetterDisplay installed:** `betterdisplaycli help` should succeed. If not:
   `brew install --cask betterdisplay` then `open -ga BetterDisplay`.
2. **TCC permissions granted to the app that runs your terminal commands**
   (e.g. Zed, Terminal, iTerm). These are user-only grants — you cannot set them
   programmatically. If a step fails, tell the user to enable the app and relaunch it:
   - **Screen Recording** — needed to screenshot the virtual display.
     `open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'`
   - **Accessibility** — needed to move/click windows via System Events.
     `open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'`

Detect the app to grant by walking the process tree
(`ps -o ppid=,comm= -p <pid>`); the terminal commands run as a child of it.

## Workflow

Run these with `bash <skill_dir>/scripts/<name>.sh`, where `<skill_dir>` is the
directory containing this SKILL.md.

1. **Create the display** (idempotent; prints the arrangement):
   ```sh
   bash scripts/create.sh [DisplayName]
   ```
   Note the printed geometry, e.g. `id=3 origin=(1440,0) size=2560x1440`. The
   virtual display owns global x from its origin onward. Any window with x ≥ that
   origin is invisible on the user's built-in screen.

2. **Open an app directly on it, with no flash on the user's screen:**
   ```sh
   bash scripts/run-on-vdisplay.sh "AppName" [X] [Y] [ProcessName]
   ```
   Pass X ≥ the virtual display's origin.x from step 1 (default 1500). Pass
   `ProcessName` when the System Events process name differs from the app name
   (e.g. app `Visual Studio Code` -> process `Code`).

   The script launches the app **hidden** (`open -gj`) so its window is never
   drawn, moves the window onto the virtual display while still hidden, then
   reveals it there. This avoids the window briefly appearing on the user's screen
   that a launch-then-move approach causes. The app must not already be running —
   quit it first if needed so it can be relaunched hidden.

   Works for apps that open a window on launch (Calculator, Safari, most apps).
   Some document apps (e.g. TextEdit) do not auto-open a window; for those, create
   the window while the app is still hidden, then position and reveal:
   ```sh
   open -gj -a TextEdit
   osascript -e 'tell application "TextEdit" to make new document'
   osascript -e 'tell application "System Events" to tell process "TextEdit" to set position of window 1 to {1600,150}'
   osascript -e 'tell application "TextEdit" to activate'
   ```

3. **Screenshot only the virtual display** (`-D 2` = secondary display):
   ```sh
   bash scripts/capture.sh /tmp/shot.png
   ```
   To view the image yourself, copy it into the current project first
   (`read_file` only reads project paths), then read it, then delete the copy —
   screenshots of a Retina virtual display are large (~15 MB).

4. **Tear down when finished:**
   ```sh
   bash scripts/destroy.sh [DisplayName]
   ```

## Opening/positioning windows without the helper

To open an app off-screen with no flash, replicate the hidden-launch technique:
```sh
open -gj -a "AppName"                 # launch hidden + background (window not drawn)
# wait for `count windows` >= 1 via System Events, then, while still hidden:
osascript -e 'tell application "System Events" to tell process "AppName" to set position of window 1 to {1600, 150}'
osascript -e 'tell application "AppName" to activate'   # reveal, already on virtual display
```
Read app state back the same way (`get value of ...`) or via screenshot + your own
inspection.

## Notes and limitations

- The virtual display is **not persistent across reboots** — re-run `create.sh`.
- Do not make the virtual display the *main* display on a laptop the user is
  actively using: it moves the menu bar/Dock and disrupts them. Prefer launching
  then repositioning windows.
- Customize resolution on `create.sh` via BetterDisplay params, e.g.
  `betterdisplaycli create -type=VirtualScreen -name=Test -useResolutionList=on -resolutionList=1920x1080`.
- Clean up demo windows/apps you open (e.g. quit the app, close docs without saving)
  so you don't leave clutter in the user's session.
- Move the pointer only through `bash scripts/with-cursor-parked.sh <cmd>` (or a
  self-parking takeover script), so the cursor always ends at the center of the
  user's primary physical display without you having to remember to park it.
- Always confirm each step's exit status; a silent failure usually means a missing
  TCC permission or that BetterDisplay isn't running.
