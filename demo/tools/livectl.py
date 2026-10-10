"""Drive Live on the rig for the demo footage. Run inside hands' environment:

  cd hands && uv run python ../demo/tools/livectl.py open        # copy HW002_121_full, save the current set, open the copy
  cd hands && uv run python ../demo/tools/livectl.py x "song.tempo"
  cd hands && uv run python ../demo/tools/livectl.py menu View "Zoom In Time"
  cd hands && uv run python ../demo/tools/livectl.py win          # Live frontmost, clear of the Dock
  cd hands && uv run python ../demo/tools/livectl.py shot out.png
  cd hands && uv run python ../demo/tools/livectl.py restore      # reopen the set that was open before

Same rules as hands/scripts/arrange_prototype: work on a copy inside the HW002
project folder, save the open set before switching, check the front window.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import time

from hands.transport import LiveMcpTransport

PROJ = pathlib.Path.home() / "_agent_scratch/HW002"
SRC = PROJ / "HW002_121_full.als"
COPY = PROJ / "HW002_121_v_demo-film.als"
STATE = pathlib.Path(__file__).resolve().parent.parent / "out/live_state.json"
APP = "Ableton Live 12 Suite"
T = LiveMcpTransport()
# Live's window: full width, below the menu bar, above the Dock
WIN = (0, 25, 1920, 955)


def r(code: str):
    x = T.execute(code)
    if x.status != "ok":
        raise RuntimeError(f"{code[:80]!r}: {x.error}")
    return x.result


def osa(script: str) -> str:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30).stdout.strip()


def menu(menu_name: str, item: str, tries: int = 6) -> bool:
    for _ in range(tries):
        en = osa(f'tell application "System Events" to tell process "Live" to get enabled of menu item "{item}" of menu "{menu_name}" of menu bar 1')
        if en == "true":
            osa(f'tell application "System Events" to tell process "Live" to click menu item "{item}" of menu "{menu_name}" of menu bar 1')
            return True
        time.sleep(0.4)
    return False


def front() -> str:
    return osa('tell application "System Events" to get name of front window of process "Live"')


def wait_for(name: str) -> None:
    for _ in range(120):
        time.sleep(1)
        if front() == name:
            break
    else:
        raise RuntimeError(f"Live did not open {name}; front window is {front()!r}")
    for _ in range(30):
        try:
            r("song.tempo")
            return
        except RuntimeError:
            time.sleep(1)


def win() -> None:
    x, y, w, h = WIN
    osa('tell application "Ableton Live 12 Suite" to activate')
    time.sleep(0.5)
    osa(f'tell application "System Events" to tell process "Live" to set position of front window to {{{x}, {y}}}')
    osa(f'tell application "System Events" to tell process "Live" to set size of front window to {{{w}, {h}}}')


def open_copy() -> None:
    before = front()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"before": before}))
    shutil.copy2(SRC, COPY)
    menu("File", "Save Live Set")
    time.sleep(1.5)
    subprocess.run(["open", "-a", APP, str(COPY)], check=True)
    wait_for(COPY.stem)
    win()
    print(f"was {before!r}, now {front()!r}")


def restore() -> None:
    before = json.loads(STATE.read_text())["before"]
    r("song.stop_playing()")
    path = PROJ / f"{before}.als"
    subprocess.run(["open", "-a", APP, str(path)], check=True)
    # the copy is scratch: answer "Save changes?" with Don't Save
    for _ in range(20):
        time.sleep(1)
        if front() == before:
            break
        osa('tell application "System Events" to tell process "Live" to if exists button "Don\'t Save" of front window then click button "Don\'t Save" of front window')
    wait_for(before)
    print(f"reopened {front()!r}")


def shot(path: str) -> None:
    subprocess.run(["screencapture", "-x", "-D", "1", path], check=True)
    print(path)


def main() -> None:
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "open":
        open_copy()
    elif cmd == "restore":
        restore()
    elif cmd == "x":
        print(json.dumps(r(args[0])))
    elif cmd == "menu":
        print(menu(args[0], args[1]))
    elif cmd == "win":
        win()
    elif cmd == "shot":
        shot(args[0])
    elif cmd == "front":
        print(front())


if __name__ == "__main__":
    main()
