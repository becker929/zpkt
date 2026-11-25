"""The desk's monitor tracks in Live: the original render and the four references, as audio in the Arrangement.

    uv run python contrib/mixdesk/monitor.py ensure     # add what is missing (idempotent)
    uv run python contrib/mixdesk/monitor.py remove     # delete them again (do this before a render you keep)

"mon A" holds the original render (A.wav) and "mon B" the recipe's render (B.wav) at beat 0; "mon C1".."mon C4" hold the reference clips at the drop (beat 64 =
bar 17), warping off. All of them stay MUTED unless the desk is monitoring them (pager.monitor), so a render of the set
never doubles. The files are the WAVs analyze.py wrote. Each step is one short LOM call, as the ableton guide asks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from zpkt.live import monitor_tracks as tracks
from zpkt.live.transport import LiveClient, McpTransport

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


def ensure(live: McpTransport | None = None, log=print, want: dict[str, tuple[Path, float]] | None = None) -> None:
    """Add the monitor tracks that are missing. `want` ({name: (wav, beat)}) defaults to sources.json's; the
    recipe passes its own, so a rebuilt set gets the tracks the recipe was written with. The work is zpkt.live's."""
    try:
        tracks.ensure(live or LiveClient(timeout=10.0, retries=1), want or wanted(), log)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None


def remove(live: McpTransport | None = None) -> None:
    tracks.remove(live or LiveClient(timeout=10.0, retries=1))


def status(live: McpTransport | None = None) -> list:
    return tracks.status(live or LiveClient(timeout=10.0, retries=1))


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "ensure":
        ensure()
    elif step == "remove":
        remove()
    elif step != "status":
        sys.exit(__doc__)
    print(json.dumps(status(), indent=1))
