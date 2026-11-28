"""Songs: make a new one, save it, save it under another name, open another (Anthony, 27 November 2026).

A song is a Live set in the rig's sets_dir. The ones the app knows are listed in `<sets_dir>/songs.json`, with the
title the person gave and whether the mix desk's own pages and reference tracks belong to it (`desk`: the HW002 sets
that `contrib/mixdesk/sources.json` was written for). A new song's file is `song_<title in letters>.als`, so the
rig's guards take it as one of ours (`set_prefixes` must hold `song_`).

The desk follows the song: after a new, a save as or an open it is moved onto that set (`Desk.use_song`), so its
History, checkpoints, surfaces and the wrong-set guard are that song's. Each command saves the song in front first
when it is one of the files here, so Live never asks about unsaved changes and nothing is lost.

Commands (zpkt.app.effects): `song.list` is a read; `song.new`, `song.save`, `song.save_as` and `song.open` are moves:
an agent cannot change which song is open (the agent rule refuses its moves).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app.bus import BadRequest, Command, Reply
from zpkt.live import config, export, openset, session, ui

if TYPE_CHECKING:
    from zpkt.app.bus import Bus
    from zpkt.app.desk import Desk

PREFIX = "song_"
MAX_TITLE = 48


def index_file() -> Path:
    return config.rig().sets_dir / "songs.json"


def read_index(path: Path | None = None) -> dict[str, Any]:
    """{"current": the song the desk is on (or None), "songs": [{"name", "title", "desk"}]}."""
    path = path or index_file()
    try:
        data: dict[str, Any] = json.loads(path.read_text())
    except FileNotFoundError:
        data = {}
    data.setdefault("current", None)
    data.setdefault("songs", [])
    return data


def write_index(data: dict[str, Any], path: Path | None = None) -> None:
    path = path or index_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def file_name(title: str) -> str:
    """The set's name for a title: song_ and the title's letters and digits, lower case, joined by _."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    if not words:
        raise BadRequest("give the song a name with at least one letter or digit")
    return PREFIX + "_".join(words)[:MAX_TITLE]


def clean_title(raw: Any) -> str:
    title = " ".join(str(raw or "").split())
    if not title:
        raise BadRequest("give the song a name")
    if len(title) > MAX_TITLE:
        raise BadRequest(f"a song's name has at most {MAX_TITLE} letters")
    return title


def entry(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((s for s in data["songs"] if s["name"] == name), None)


def remember(name: str, title: str | None = None, desk: bool | None = None, path: Path | None = None) -> None:
    """Put `name` in the index (once) and make it the current song."""
    data = read_index(path)
    e = entry(data, name)
    if e is None:
        e = {"name": name, "title": title or name, "desk": bool(desk)}
        data["songs"].append(e)
    else:
        if title:
            e["title"] = title
        if desk is not None:
            e["desk"] = desk
    data["current"] = name
    write_index(data, path)


def is_desk_song(name: str, home: str, path: Path | None = None) -> bool:
    """Whether the mix desk's own pages and reference tracks belong to this set: the set sources.json names, or one
    the index marks so (a copy of it)."""
    if name == home:
        return True
    e = entry(read_index(path), name)
    return bool(e and e.get("desk"))


def listing(desk: Desk) -> dict[str, Any]:
    """The songs the app knows, newest file first, with the one the desk is on."""
    data = read_index()
    sets = config.rig().sets_dir
    rows = []
    for s in data["songs"]:
        f = sets / f"{s['name']}.als"
        if not f.exists():
            continue
        rows.append({**s, "modified": f.stat().st_mtime, "current": s["name"] == desk.settings.set_name})
    rows.sort(key=lambda r: -r["modified"])
    return {"current": desk.settings.set_name, "songs": rows}


# ---- the steps in Live ----------------------------------------------------------------------------------------------
def _front() -> str:
    try:
        return ui.front_title() or ""
    except ui.UiError:
        return ""


def _save_front() -> bool:
    """Save the set in front when it is a file in sets_dir. False when there was nothing to save or it is not ours."""
    front = _front()
    if not front or not config.rig().set_path(front).exists():
        return False
    return session.save(front)


def _wait(test: Callable[[], bool], seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while not test():
        if time.monotonic() > deadline:
            raise session.Guard(f"{what} did not happen in {seconds:g} s")
        time.sleep(0.2)


def _new_empty_set(conn: Any) -> None:
    """File > New Live Set, after the set in front was saved: Live shows an empty, unnamed set."""
    before = _front()
    if not ui.menu("File", "New Live Set"):
        raise session.Guard("File > New Live Set stayed disabled")
    _wait(lambda: _front() != before or session._discard_prompt(), 30, "a new empty set")
    _wait(lambda: _front() != before, 30, "a new empty set")
    _wait(lambda: _answers(conn), 30, "Live answering in the new set")


def _answers(conn: Any) -> bool:
    try:
        conn.run("result = 1")
        return True
    except Exception:
        return False


# ---- the commands ---------------------------------------------------------------------------------------------------
def song_list(desk: Desk, cmd: Command) -> Reply:
    return 200, listing(desk)


def song_new(desk: Desk, cmd: Command) -> Reply:
    title = clean_title(cmd.args.get("title"))
    name = file_name(title)
    rig = config.rig()
    if rig.set_path(name).exists():
        raise BadRequest(f"there is a song called {title} already; open it, or choose another name")
    if not rig.is_ours(name):
        raise BadRequest(f"the rig does not take {PREFIX}… sets as its own: add {PREFIX!r} to set_prefixes")
    try:
        _save_front()
        _new_empty_set(desk.conn)
        export.save_as(rig.sets_dir, name, project=False)
    except (session.Guard, ui.UiError) as exc:
        return 409, {"error": str(exc)}
    remember(name, title, desk=False)
    desk.use_song(name)
    return 200, {"ok": True, "name": name, "title": title, **listing(desk)}


def song_save(desk: Desk, cmd: Command) -> Reply:
    front = _front()
    if front != desk.settings.set_name:
        return 409, {"error": f"Live has {front or 'an unsaved set'} open, not {desk.settings.set_name}"}
    try:
        saved = session.save(front)
    except session.Guard as exc:
        return 409, {"error": str(exc)}
    return 200, {"ok": True, "saved": saved, "name": front}


def song_save_as(desk: Desk, cmd: Command) -> Reply:
    title = clean_title(cmd.args.get("title"))
    name = file_name(title)
    rig = config.rig()
    if rig.set_path(name).exists():
        raise BadRequest(f"there is a song called {title} already; choose another name")
    was = desk.settings.set_name
    try:
        export.save_as(rig.sets_dir, name, project=False)
    except (session.Guard, ui.UiError) as exc:
        return 409, {"error": str(exc)}
    remember(name, title, desk=is_desk_song(was, desk.home_set))
    desk.use_song(name)
    return 200, {"ok": True, "name": name, "title": title, **listing(desk)}


def song_open(desk: Desk, cmd: Command) -> Reply:
    name = str(cmd.args.get("name") or "").removesuffix(".als")
    if entry(read_index(), name) is None:
        raise BadRequest(f"no song called {name}")
    if _front() == name:  # Live will not reload the set it has: the desk just follows it
        desk.use_song(name)
        remember(name)
        return 200, {"ok": True, "name": name, "seconds": 0.0, **listing(desk)}
    try:
        seconds = session.open_set(desk.conn, name, save_current=True)
    except session.Guard as exc:
        return 409, {"error": str(exc)}
    remember(name)
    desk.use_song(openset.open_set_name(desk.conn) or name)
    return 200, {"ok": True, "name": name, "seconds": round(seconds, 2), **listing(desk)}


COMMANDS = {
    "song.list": (song_list, False),
    "song.new": (song_new, True),
    "song.save": (song_save, True),
    "song.save_as": (song_save_as, True),
    "song.open": (song_open, True),
}


def register(bus: Bus, desk: Desk) -> None:
    for kind, (handler, touches) in COMMANDS.items():

        def run(cmd: Command, handler: Callable[[Desk, Command], Reply] = handler) -> Reply:
            return handler(desk, cmd)

        spec: dict[str, Any] = {"touches_live": touches}
        if touches:
            spec["guarded"] = False  # they are how Live gets to a set; an agent is refused by the agent rule
        effects.register(bus, kind, run, **spec)


__all__ = ["COMMANDS", "PREFIX", "file_name", "listing", "read_index", "register", "remember"]
