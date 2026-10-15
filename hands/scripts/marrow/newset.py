"""Start the Marrow cumbia set: File > New Live Set, saved (no keystrokes) where the Save panel can reach, then copied
into ~/_agent_scratch/marrow/set/ and opened from there, so the set is Live 12-native and lives in its own folder.

  cd hands && uv run python scripts/marrow/newset.py
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402  - the rig environment first
from ops import L  # noqa: E402
from hands.live import session, ui  # noqa: E402

SEED = "MARROW_seed"
REACHABLE = Path("~/_agent_scratch/rummage/set").expanduser()   # the Save panel's Recent Places include it


def main() -> None:
    if ui.menu_enabled("File", "Save Live Set"):
        sys.exit(f"STOP: {ui.front_title()} has unsaved changes; save it first")
    target = ops.SET_DIR / f"{ops.SET_NAME}.als"
    if target.exists():
        sys.exit(f"STOP: {target} exists already")
    if not ui.menu("File", "New Live Set"):
        sys.exit("STOP: File > New Live Set stayed disabled")
    for _ in range(40):
        if ui.front_title() == "Untitled":
            break
        time.sleep(0.25)
    else:
        sys.exit(f"STOP: no new set in front ({ui.windows()})")
    time.sleep(1.0)
    if ui.dialogs():
        sys.exit(f"STOP: a dialog after New Live Set: {ui.windows()}")
    seed = L.save_as(REACHABLE, SEED)
    print("seed:", seed)
    ops.SET_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(seed.parent, ops.SET_DIR)
    (ops.SET_DIR / f"{SEED}.als").rename(target)
    session.open_set(L.LIVE, ops.SET_NAME, save_current=False)
    print("front:", ui.front_title(), "tracks:", L.run("result = [t.name for t in song.tracks]"))


if __name__ == "__main__":
    main()
