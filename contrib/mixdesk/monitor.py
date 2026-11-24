"""The desk's monitor tracks in Live: the original render and the four references, as audio in the Arrangement.

    uv run --project hands python contrib/mixdesk/monitor.py ensure     # add what is missing (idempotent)
    uv run --project hands python contrib/mixdesk/monitor.py remove     # delete them again (do this before a render you keep)

"mon A" holds the original render (A.wav) and "mon B" the recipe's render (B.wav) at beat 0; "mon C1".."mon C4" hold the reference clips at the drop (beat 64 =
bar 17), warping off. All of them stay MUTED unless the desk is monitoring them (pager.monitor), so a render of the set
never doubles. The files are the WAVs analyze.py wrote. Each step is one short LOM call, as the ableton guide asks.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from hands.live.transport import LiveClient

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "sources.json").read_text())
VIZ = Path(CFG["dir"]).expanduser()
BEATS_PER_S = 160.0 / 60.0
ALIGN_BEAT = float(CFG["ref_align_s"]) * BEATS_PER_S


def wanted() -> dict[str, tuple[Path, float]]:
    w = {"mon A": (VIZ / "A.wav", 0.0), "mon B": (VIZ / "B.wav", 0.0)}
    for r in CFG["refs"]:
        w[f"mon {r['id']}"] = (VIZ / f"{r['id']}.wav", ALIGN_BEAT)
    return w


def ensure(live: LiveClient | None = None, log=print, want: dict[str, tuple[Path, float]] | None = None) -> None:
    """Add the monitor tracks that are missing. `want` ({name: (wav, beat)}) defaults to sources.json's; the
    recipe passes its own, so a rebuilt set gets the tracks the recipe was written with."""
    live = live or LiveClient(timeout=10.0, retries=1)
    for name, (wav, beat) in (want or wanted()).items():
        if not wav.exists():
            raise SystemExit(f"missing {wav}: run analyze.py")
        have = live.run("result = [t.name for t in song.tracks]")
        if name not in have:
            live.run("song.create_audio_track(-1)\nresult = 'ok'")
            time.sleep(0.3)
            n = live.run("result = len(song.tracks)") - 1
            live.run(f"song.tracks[{n}].name = {name!r}\nresult = 'ok'")
            log("added", name)
        i = live.run(f"result = [t.name for t in song.tracks].index({name!r})")
        n_clips = live.run(f"result = len(list(song.tracks[{i}].arrangement_clips))")
        if n_clips == 0:
            live.run(f"song.tracks[{i}].create_audio_clip({str(wav)!r}, {beat})\nresult = 'ok'")
            time.sleep(0.4)
            log("clip", name)
        # warping off (a file of its own length must not be stretched), muted unless monitored
        live.run(f"for c in song.tracks[{i}].arrangement_clips:\n    c.warping = False\nresult = 'ok'")
        live.run(f"song.tracks[{i}].mute = True\nresult = 'ok'")
        time.sleep(0.2)


def remove(live: LiveClient | None = None) -> None:
    live = live or LiveClient(timeout=10.0, retries=1)
    while True:
        idx = [i for i, n in enumerate(live.run("result = [t.name for t in song.tracks]")) if n.startswith("mon ")]
        if not idx:
            return
        live.run(f"song.delete_track({idx[-1]})\nresult = 'ok'")
        time.sleep(0.3)


def status(live: LiveClient | None = None) -> list:
    live = live or LiveClient(timeout=10.0, retries=1)
    return live.run(
        "result = [[t.name, t.mute, t.solo, [(c.file_path.split('/')[-1], c.start_time, c.end_time, c.warping) for c in t.arrangement_clips]] "
        "for t in song.tracks if t.name.startswith('mon ')]"
    )


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "ensure":
        ensure()
    elif step == "remove":
        remove()
    elif step != "status":
        sys.exit(__doc__)
    print(json.dumps(status(), indent=1))
