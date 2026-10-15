"""Start the industrial short's set from HW002's, keeping only its device chains: the plugins (COLDFIRE, Decapitator,
LFOTool, Supermassive, FlexVerb, StandardCLIP, GClip) are already configured there, so the LOM can reach their knobs.

Offline, on the .als (gzipped XML), with no Live involved: every arrangement and session clip goes, every automation
envelope (tracks, returns, Main), the locators; the samples the drum racks use are copied into the new project and
their paths pointed there. The tracks themselves stay (deleting one here could leave a dangling routing): make.py
deletes the unused ones in Live, which fixes routings as it goes.

  cd hands && uv run python scripts/industrial/strip.py
"""
from __future__ import annotations

import gzip
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402

SOURCE = Path("~/_agent_scratch/HW002/HW002_121_full.als").expanduser()
SAMPLES = ops.SET_DIR / "Samples" / "Imported"


def strip(root: ET.Element) -> dict:
    ls = root.find("LiveSet")
    n = {"clips": 0, "envelopes": 0, "slots": 0, "samples": 0}
    for events in ls.iter("Events"):                     # arrangement clips (MainSequencer, FreezeSequencer)
        clips = [c for c in events if c.tag in ("MidiClip", "AudioClip")]
        for c in clips:
            events.remove(c)
        n["clips"] += len(clips)
    for envs in ls.iter("Envelopes"):                    # inside clips they went with the clips; these are tracks'
        n["envelopes"] += len(envs)
        for e in list(envs):
            envs.remove(e)
    for slot in ls.iter("ClipSlot"):
        v = slot.find("Value")
        if v is not None and len(v):
            n["slots"] += 1
            for c in list(v):
                v.remove(c)
    loc = ls.find("Locators/Locators")
    for c in list(loc):
        loc.remove(c)
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for fr in ls.iter("FileRef"):
        p = fr.find("Path")
        if p is None or not p.get("Value", "").lower().endswith((".wav", ".aif", ".aiff")):
            continue
        src = Path(p.get("Value"))
        local = SOURCE.parent / "Samples" / "Imported" / src.name
        if not src.exists() and local.exists():
            src = local
        if not src.exists() or "/App-Resources/" in str(src):
            continue
        dst = SAMPLES / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        p.set("Value", str(dst))
        rel = fr.find("RelativePath")
        if rel is not None:
            rel.set("Value", f"Samples/Imported/{src.name}")
        rt = fr.find("RelativePathType")
        if rt is not None:
            rt.set("Value", "3")                         # relative to the project
        n["samples"] += 1
    return n


def main() -> None:
    target = ops.SET_DIR / f"{ops.SET_NAME}.als"
    if target.exists():
        sys.exit(f"STOP: {target} exists already")
    root = ET.fromstring(gzip.open(SOURCE).read())
    n = strip(root)
    info = ops.SET_DIR / "Ableton Project Info"
    if not info.exists():
        shutil.copytree(SOURCE.parent / "Ableton Project Info", info)
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
    with gzip.open(target, "wb") as f:
        f.write(data)
    check = ET.fromstring(gzip.open(target).read()).find("LiveSet")
    left = sum(1 for t in (check.find("Tracks"), check.find("MainTrack")) for e in t.iter()
               if e.tag in ("MidiClip", "AudioClip"))       # the groove pool's clips are grooves, and stay
    if left:
        sys.exit(f"STOP: {left} clips left in {target}")
    print(target, n, "tracks:", [t.find("Name/EffectiveName").get("Value") for t in check.find("Tracks")])


if __name__ == "__main__":
    main()
