"""Bounce and measure: how an agent hears. The app's two commands for rendered audio.

    render.bounce {what, bars, name}      the mix, or up to four tracks, groups or returns, over a range of bars: one
                                          WAV each in the bounce folder, and each file's short sheet in the answer
    render.measure {file, against, bars, seconds, detail}
                                          one view of one window of an audio file (a bounce, a reference, a file in
                                          home), and the difference to a second file; with no file, the bounces kept

An agent must not load audio, or a long analysis, into its conversation: megabytes of nothing. So a bounce answers
with about twenty numbers per file (zpkt.audio.brief) and the file's path, which the chat's `audio` block plays, and
`render.measure` gives one more view at a time: the third octaves, or the level bar by bar.

`render.bounce` is a move that an agent may ask for on its own (zpkt.app.effects has the reason). It takes Live for
the export (about 13 s a file and 0.1 s per second of audio), and what it changes it puts back: the loop, and the Pin
when the Pin was heard. It changes no value of the mix and leaves no History row and no version. Three things it does
not put back, and says in its answer: playback stays stopped, a reference that was heard stays left (Now is heard),
and the time selection is the range bounced.

A bounce is always of Now. A reference that is heard solos its own track and bypasses Main's devices, and the Pin
writes other values into the mix: either would be bounced in place of what was asked for, so Now is heard first.
Solos and mutes are left as they are, since they are part of the mix as it stands: the answer names the soloed
tracks, and a file with next to nothing in it says `silent`.

The bounces are kept in <renders folder>/bounce, each with a small .json beside it that says what it is (the bars,
the tempo), so a later `render.measure` can be asked in bars. The oldest go when the folder holds more than
KEEP_BYTES.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app.bus import BadRequest, Bus, Command, Refused, Reply
from zpkt.audio import brief
from zpkt.live import bounce as live_bounce
from zpkt.live import config, session, ui
from zpkt.live import steps as live_steps

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

log = logging.getLogger(__name__)

FOLDER = "bounce"  # inside the rig's renders folder
MAX_FILES = 4  # of one bounce
MAX_AUDIO_S = 600.0  # of one bounce, all its files together
KEEP_BYTES = 2_000_000_000  # the folder's size; the oldest bounces go first
LISTED = 12  # bounces in a listing
AUDIO = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg")
DETAILS = ("summary", "spectrum", "over_time")
MIX_WORDS = ("mix", "main", "master")
MONITOR_PREFIX = live_steps.MONITOR_PREFIX
FAILED = 409  # the export did not write the file: the answer says why, and which files were written before


def folder() -> Path:
    return config.rig().renders_dir / FOLDER


@contextlib.contextmanager
def measuring() -> Iterator[None]:
    """Around zpkt.audio.brief: a file or a window it cannot measure is the caller's 400."""
    try:
        yield
    except brief.BriefError as exc:
        raise BadRequest(str(exc)) from None


def tidy(n: float) -> float | int:
    """A bar or a second as it is said: 17, not 17.0; 17.5 stays."""
    r = round(float(n), 3)
    return int(r) if r == int(r) else r


# ---- a bounce: reading the ask -------------------------------------------------------------------------------------


def names_asked(args: Any) -> list[str]:
    what = args.get("what", live_bounce.MIX)
    asked = [what] if isinstance(what, str) else what
    if not isinstance(asked, list) or not asked or not all(isinstance(n, str) and n.strip() for n in asked):
        raise BadRequest(
            f"'what' is \"mix\" (Main's output), the name of a track, group or return, or a list of up to {MAX_FILES}"
        )
    names = list(dict.fromkeys(n.strip() for n in asked))
    if len(names) > MAX_FILES:
        raise BadRequest(f"one bounce is at most {MAX_FILES} files; ask for the others in a second call")
    return names


def the_tracks(names: list[str], tracks: list[live_bounce.Track]) -> list[live_bounce.Track | None]:
    """Each asked name as the set's own track (None: Main's output). The rail: never a monitor track."""
    ours = [t for t in tracks if not t["name"].startswith(MONITOR_PREFIX)]
    found: list[live_bounce.Track | None] = []
    for name in names:
        if name.startswith(MONITOR_PREFIX):
            raise Refused(f"{name!r} is one of the monitor's tracks: it is not bounced")
        same = [t for t in ours if t["name"] == name] or [t for t in ours if t["name"].lower() == name.lower()]
        if len(same) > 1:
            raise BadRequest(f"the set has {len(same)} tracks named {name!r}: Live's export goes by the name")
        if same:
            found.append(same[0])
        elif name.lower() in MIX_WORDS:
            found.append(None)
        else:
            raise BadRequest(
                f'no track, group or return named {name!r}. "mix" is Main\'s output; the set has: '
                + ", ".join(t["name"] for t in ours)
            )
    return found


def the_range(args: Any, facts: live_bounce.Facts) -> tuple[float, float]:
    """(start, length) in beats of what `bars` says: "loop", "song" or [first, last] (bars count from 1, both ends
    in). With nothing said, the loop when it is on, else the song."""
    per_bar = facts["beats_per_bar"]
    end = math.ceil(facts["end"] / per_bar - 1e-9) * per_bar  # the song, to the end of its last bar
    bars = args.get("bars")
    if bars is None:
        bars = "loop" if facts["loop"]["on"] else "song"
    if bars == "loop":
        start, length = float(facts["loop"]["start"]), float(facts["loop"]["length"])
    elif bars == "song":
        start, length = 0.0, end
    elif (
        isinstance(bars, list)
        and len(bars) == 2
        and all(isinstance(b, int) and not isinstance(b, bool) for b in bars)
        and 1 <= bars[0] <= bars[1]
    ):
        start, length = (bars[0] - 1) * per_bar, (bars[1] - bars[0] + 1) * per_bar
    else:
        raise BadRequest('\'bars\' is "loop", "song" or [first, last]: whole bars counted from 1, both included')
    if end <= 0:
        raise BadRequest("the Arrangement is empty: there is nothing to bounce")
    if start >= end:
        raise BadRequest(f"the song ends after bar {tidy(end / per_bar)}: bar {tidy(start / per_bar + 1)} is past it")
    return start, length


def bars_of(start: float, length: float, per_bar: float) -> list[float | int]:
    """[first, last] as the_range reads it."""
    return [tidy(start / per_bar + 1), tidy((start + length) / per_bar)]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


def new_path(stamp: str, label: str, bars: list[float | int]) -> Path:
    """A name no file has: Live's export refuses a name that is taken."""
    base = f"{stamp}-{slug(label)}-bars-{bars[0]}-{bars[1]}".replace(".", "_")
    path, n = folder() / f"{base}.wav", 1
    while path.exists() or path.with_suffix(".json").exists():
        n += 1
        path = folder() / f"{base}-{n}.wav"
    return path


def prune(keep_bytes: int = KEEP_BYTES) -> None:
    """The oldest bounces go, each with its .json, until the folder is under `keep_bytes`."""
    files = sorted((f for f in folder().glob("*.wav") if f.is_file()), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    for f in files[:-1]:  # never the newest
        if total <= keep_bytes:
            break
        total -= f.stat().st_size
        f.unlink(missing_ok=True)
        f.with_suffix(".json").unlink(missing_ok=True)


# ---- a bounce --------------------------------------------------------------------------------------------------------


def bounce(desk: Desk, cmd: Command) -> Reply:
    """Bounce the mix or named tracks over a range of bars; the answer has each file's path and short sheet."""
    args = cmd.args
    names = names_asked(args)
    label = args.get("name")
    if label is not None and not (isinstance(label, str) and label.strip()):
        raise BadRequest("'name' is a word or two for the file's name")
    began = time.monotonic()
    found = live_bounce.facts(desk.conn)
    chosen = the_tracks(names, found["tracks"])
    was_hearing = str(desk.monitor.message()["hearing"])
    files: list[dict[str, Any]] = []
    exported = False
    try:
        if was_hearing != "now":
            desk.monitor.hear("now")
            found = live_bounce.facts(desk.conn)  # the reference had its own loop; this is the mix's again
        start, length = the_range(args, found)
        per_bar, tempo = found["beats_per_bar"], found["tempo"]
        seconds = length * 60.0 / tempo
        if seconds * len(chosen) > MAX_AUDIO_S:
            raise BadRequest(
                f"{len(chosen)} file(s) of {seconds:.0f} s are more than {MAX_AUDIO_S:g} s of audio in one bounce: "
                "ask for fewer bars or fewer tracks"
            )
        if found["playing"]:
            live_bounce.facts(desk.conn, stop_playing=True)
        bars = bars_of(start, length, per_bar)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for track in chosen:
            what = live_bounce.MIX if track is None else track["name"]
            out = new_path(stamp, f"{label.strip()} {what}" if label else what, bars)
            exported = True
            try:
                live_bounce.bounce(desk.conn, out, start, length, track=None if track is None else track["name"])
            except (session.Guard, ui.UiError, ValueError) as exc:
                return FAILED, {"error": f"the bounce of {what} failed: {str(exc)[:300]}", "files": files}
            meta = {
                "what": what,
                "bars": bars,
                "start_beat": start,
                "length_beats": length,
                "tempo": tempo,
                "beats_per_bar": per_bar,
                "set": desk.settings.set_name,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            out.with_suffix(".json").write_text(json.dumps(meta))
            with measuring():
                sheet = brief.brief(out)
            files.append(
                {
                    "what": what,
                    "file": str(out),
                    "bars": bars,
                    **sheet,
                    **({"muted": True} if track and track["mute"] else {}),
                }
            )
    finally:
        put_back(desk, found["loop"] if exported else None, was_hearing)
    prune()
    soloed = [t["name"] for t in found["tracks"] if t["solo"] and not t["name"].startswith(MONITOR_PREFIX)]
    return 200, {
        "ok": True,
        "files": files,
        "tempo": tidy(found["tempo"]),
        "took_s": round(time.monotonic() - began, 1),
        "hearing": "pin" if was_hearing == "pin" else "now",
        **({"was_hearing": was_hearing} if was_hearing not in ("now", "pin") else {}),
        **({"stopped_playback": True} if found["playing"] else {}),
        **({"soloed": soloed} if soloed else {}),
    }


def put_back(desk: Desk, loop: dict[str, Any] | None, was_hearing: str) -> None:
    """After a bounce, also one that failed: the loop as it was, and the Pin if it was heard. What cannot be put
    back is in the log, never in the way of the answer."""
    try:
        if loop is not None:
            live_steps.loop_put(desk.conn, loop)
        if was_hearing == "pin":
            desk.monitor.hear("pin")
    except Exception as exc:
        log.error("app: after a bounce, the loop or the Pin was not put back (%s)", type(exc).__name__)


# ---- measuring: which file, which window ---------------------------------------------------------------------------


def references() -> dict[str, dict[str, Any]]:
    """The desk's references and renders by id ("C1", "A"), from sources.json: {"file", "what", and the grid}."""
    from zpkt.app.desk import read_sources

    try:
        sources = read_sources()
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in [*sources.get("refs", []), *sources.get("mixes", [])]:
        if not isinstance(r, dict) or not r.get("id") or not r.get("file"):
            continue
        meta: dict[str, Any] = {"what": f"{r.get('label') or r['id']} ({r['id']})"}
        if r.get("bpm") and r.get("bars"):  # a reference's cut starts on a downbeat and holds whole bars of its own
            meta.update(tempo=float(r["bpm"]), beats_per_bar=4.0, bars=[1, int(r["bars"])])
        out[str(r["id"]).lower()] = {"file": str(r["file"]), **meta}
    return out


def the_file(text: Any, name: str = "file") -> tuple[Path, dict[str, Any]]:
    """(the audio file, what is known of it) for what a caller wrote: a bounce's name or path, a reference's id, or
    a path inside home. The second is {} for a file with no .json beside it."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise BadRequest(f"{name!r} is a bounce's file, a reference's id such as \"C1\", or a path inside home")
    text = text.strip()
    known = references().get(text.lower())
    if known is not None:
        path = Path(known["file"]).expanduser()
        if not path.is_file():
            raise BadRequest(f"the file of {known['what']} is not on this Mac")
        return path, {k: v for k, v in known.items() if k != "file"}
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = folder() / path
    try:
        real = path.resolve(strict=True)
    except OSError:
        raise BadRequest(f"no file {text!r}; render.measure with no file lists the bounces") from None
    inside = (Path.home().resolve(), folder().resolve())
    if not any(root == real.parent or root in real.parents for root in inside):
        raise Refused("only files inside the home folder are measured")
    if any(part.startswith(".") for part in real.parts):
        raise Refused("files in hidden folders are not measured")
    if real.suffix.lower() not in AUDIO or not real.is_file():
        raise BadRequest(f"{real.name} is not an audio file ({', '.join(AUDIO)})")
    return real, sidecar(real)


def sidecar(path: Path) -> dict[str, Any]:
    """What a bounce's .json says, when it is whole; else {}."""
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
    except (OSError, ValueError):
        return {}
    good = (
        isinstance(meta, dict)
        and isinstance(meta.get("bars"), list)
        and len(meta["bars"]) == 2
        and all(isinstance(meta.get(k), int | float) and meta[k] > 0 for k in ("tempo", "beats_per_bar"))
    )
    return meta if good else {}


def bar_seconds(meta: dict[str, Any]) -> float:
    return float(meta["beats_per_bar"]) * 60.0 / float(meta["tempo"])


def pair(args: Any, name: str) -> tuple[float, float] | None:
    value = args.get(name)
    if value is None:
        return None
    if not (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        raise BadRequest(f"{name!r} is [from, to]")
    return float(value[0]), float(value[1])


def the_window(args: Any, path: Path, meta: dict[str, Any]) -> tuple[float, float | None, dict[str, Any]]:
    """(start, end in seconds; None: the file's end, and how the window is said back) from `bars` or `seconds`."""
    bars, seconds = pair(args, "bars"), pair(args, "seconds")
    if bars is not None and seconds is not None:
        raise BadRequest("say the window in 'bars' or in 'seconds', not both")
    if bars is not None:
        if "tempo" not in meta:
            raise BadRequest(f"{path.name} does not say which bars it holds: give the window in 'seconds'")
        first, last = float(meta["bars"][0]), float(meta["bars"][1])
        if not first <= bars[0] <= bars[1] <= last:
            raise BadRequest(f"{path.name} holds bars {tidy(first)} to {tidy(last)}; 'bars' is [first, last] in there")
        one = bar_seconds(meta)
        return (bars[0] - first) * one, (bars[1] - first + 1) * one, {"bars": [tidy(bars[0]), tidy(bars[1])]}
    if seconds is not None:
        if not 0 <= seconds[0] < seconds[1]:
            raise BadRequest("'seconds' is [from, to], from 0 on")
        return seconds[0], seconds[1], {"seconds": [tidy(seconds[0]), tidy(seconds[1])]}
    return 0.0, None, {}


def view(path: Path, meta: dict[str, Any], start: float, end: float | None, detail: str) -> dict[str, Any]:
    """One view of the window: the short sheet, the third octaves, or the level step by step (a step is a bar when
    the file says its bars, else a second; steps are grouped so that there are at most brief.MAX_STEPS)."""
    with measuring():
        if detail == "summary":
            return brief.brief(path, start, end)
        if detail == "spectrum":
            return {"third_octaves_db": brief.spectrum(path, start, end)}
        length = (brief.seconds(path) if end is None else end) - start
        one = bar_seconds(meta) if "tempo" in meta else 1.0
        group = max(1, math.ceil(length / one / brief.MAX_STEPS - 1e-9))
        levels = brief.over_time(path, one * group, start, end)
        return {"step": {"bars" if "tempo" in meta else "seconds": group}, **levels}


# ---- measuring -------------------------------------------------------------------------------------------------------


def listing() -> dict[str, Any]:
    """The bounces kept, newest first: what each is, in a line."""
    where = folder()
    files = sorted((f for f in where.glob("*.wav") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    rows = []
    for f in files[:LISTED]:
        meta = sidecar(f)
        row: dict[str, Any] = {"file": f.name}
        if meta:
            row.update(what=meta.get("what"), bars=meta["bars"], at=meta.get("at"))
        rows.append(row)
    return {
        "ok": True,
        "folder": str(where),
        "bounces": rows,
        "count": len(files),
        "folder_mb": round(sum(f.stat().st_size for f in files) / 1e6),
        "references": sorted(r["what"] for r in references().values()),
    }


def measure(desk: Desk, cmd: Command) -> Reply:
    """One view of one window of an audio file, and with `against` the same of a second file and the difference
    (the first minus the second). With no file: the bounces kept."""
    args = cmd.args
    if args.get("file") is None:
        return 200, listing()
    detail = args.get("detail", "summary")
    if detail not in DETAILS:
        raise BadRequest(f"'detail' is one of {', '.join(DETAILS)}")
    path, meta = the_file(args["file"])
    start, end, said = the_window(args, path, meta)
    first = view(path, meta, start, end, detail)
    out: dict[str, Any] = {"ok": True, "file": str(path), **({"what": meta["what"]} if meta.get("what") else {})}
    out.update(said)
    out[detail] = first
    if args.get("against") is not None:
        other, other_meta = the_file(args["against"], "against")
        # the same bars of the song when both are bounces; a reference has bars of its own and is measured whole
        same_bars = "bars" in said and "start_beat" in meta and "start_beat" in other_meta
        o_start, o_end, o_said = the_window(args, other, other_meta) if same_bars else (0.0, None, {})
        second = view(other, other_meta, o_start, o_end, detail)
        out["against"] = {
            "file": str(other),
            **({"what": other_meta["what"]} if other_meta.get("what") else {}),
            **(o_said or {"window": "whole"}),
            detail: second,
        }
        out["difference"] = brief.difference(first, second)
    return 200, out


# ---- on the bus ------------------------------------------------------------------------------------------------------


def register(bus: Bus, desk: Desk) -> None:
    """Put the two commands on the bus. A bounce takes Live and checks before anything moves; it saves no version,
    since it changes no value (so `checks_first`, and never Bus.version). Measuring only reads files."""

    def run_bounce(cmd: Command) -> Reply:
        return bounce(desk, cmd)

    def run_measure(cmd: Command) -> Reply:
        return measure(desk, cmd)

    effects.register(bus, "render.bounce", run_bounce, touches_live=True, checks_first=True)
    effects.register(bus, "render.measure", run_measure)
