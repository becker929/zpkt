"""A track's device chain, one short call at a time: what is on it, add an audio effect, move a device, delete one.

    chain.look(live, ["Kick bus", "Main"])          # {"Kick bus": ["desk EQ", ...], "Main": [...]}; None: no such track
    chain.has_effect(live, "Saturator")             # is it in Live's browser, under Audio Effects?
    chain.add(live, "Kick bus", "Saturator", at=0)  # the index it ended at
    chain.move(live, "Kick bus", 0, 2)              # the index it landed on
    chain.delete(live, "Kick bus", 2, "Saturator")  # True if it was there and is gone

Every function takes the Live connection (the app hands it in). Each call to Live is short and never reads back what
it wrote: the reading is a call of its own (ableton-guide rules 1 and 6). The load is the one zpkt.live.mix has used
since October 2026: find the audio effect in the browser, select the track, `browser.load_item`, then ask until the
chain is longer. Live decides where a loaded device lands (after the selected device, else last), so `add` reads the
chain to learn the index and moves the device only when another one was asked for.

A track is named as everywhere in zpkt.live ("Main", a return without its letter: zpkt.live.inlive.tracks).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from zpkt.live.agent import with_prelude
from zpkt.live.inlive import tracks as named_tracks
from zpkt.live.inlive import with_source
from zpkt.live.transport import McpTransport

LOAD_POLLS = 12  # times the chain is read after a load, LOAD_POLL_S apart, before the load counts as failed
LOAD_POLL_S = 0.25
SETTLE_S = 0.3  # after a load: back-to-back browser loads race (ableton-guide rule 3)
BROWSER_BUDGET = 4000  # browser entries looked at before the search gives up (it stays well under a second)


class ChainError(RuntimeError):
    """Live did not do the step. The message says what was asked and what was found."""


def tr(name: str) -> str:
    """The Live expression for a track by name (zpkt.live.inlive.tracks has the rule)."""
    return named_tracks.track_expr(name)


_FIND = """
def _base(n):
    return n.rsplit(".", 1)[0].lower() if n.lower().endswith((".adv", ".adg")) else n.lower()
def _find(root, name, budget):
    queue = [root]
    while queue:
        node = queue.pop(0)
        for c in node.children:
            budget[0] -= 1
            if budget[0] < 0:
                return None
            if _base(c.name) == name and c.is_loadable:
                return c
            if c.is_folder:
                queue.append(c)
    return None
"""

# The load zpkt.live.mix has used since October 2026, word for word. `result` is the chain's length before it.
ADD = (
    _FIND
    + """_t = {track}
_item = _find(browser.audio_effects, {device!r}.lower(), [BUDGET])
if _item is None:
    raise ValueError("no audio effect %r in Live's browser" % {device!r})
_n = len(_t.devices)
select_track(_t)
browser.load_item(_item)
result = _n
"""
).replace("BUDGET", str(BROWSER_BUDGET))

_HAS = (
    _FIND + "result = [_find(browser.audio_effects, n.lower(), [BUDGET]) is not None for n in {names!r}]\n"
).replace("BUDGET", str(BROWSER_BUDGET))

_LOOK = """import json
out = {{}}
for name in {names!r}:
    try:
        out[name] = [d.name for d in find_track(song, name).devices]
    except LookupError:
        out[name] = None
result = json.dumps(out)"""


def look(client: McpTransport, tracks: list[str]) -> dict[str, list[str] | None]:
    """The device names on each track, in chain order; None for a track the set does not have. One call."""
    if not tracks:
        return {}
    found: dict[str, list[str] | None] = json.loads(
        client.run(with_source(_LOOK.format(names=list(dict.fromkeys(tracks))), "tracks"))
    )
    return found


def names(client: McpTransport, track: str) -> list[str]:
    """The device names on one track, in chain order."""
    return list(client.run(f"result = [d.name for d in {tr(track)}.devices]"))


def has_effect(client: McpTransport, devices: list[str]) -> dict[str, bool]:
    """Which of `devices` Live's browser has under Audio Effects (by the name the browser shows). One call each: a
    search of the browser is the slow part of a load, so each stays short on its own."""
    return {d: bool(client.run(_HAS.format(names=[d]))[0]) for d in dict.fromkeys(devices)}


def load_effect(
    client: McpTransport, track: str, device: str, pause: Callable[[float], None] = time.sleep
) -> tuple[list[str], list[str]]:
    """Load the audio effect `device` onto `track` and wait until the chain has it. Returns the chain's names before
    and after. ChainError when Live's browser has no such effect, or the chain did not grow."""
    before = names(client, track)
    n = client.run(with_prelude(ADD.format(track=tr(track), device=device)))
    after = before
    for k in range(LOAD_POLLS):
        if k:
            pause(LOAD_POLL_S)
        after = names(client, track)
        if len(after) > n:
            pause(SETTLE_S)
            return before, after
    raise ChainError(f"Live did not load {device!r} on {track!r}")


def landed(before: list[str], after: list[str]) -> int:
    """Where one new device sits in `after`, a chain that was `before`: the first place the two differ."""
    for k, name in enumerate(before):
        if k >= len(after) or after[k] != name:
            return k
    return len(before)


def add(
    client: McpTransport,
    track: str,
    device: str,
    at: int | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Add the audio effect `device` to `track`, at index `at` (None: wherever Live puts it, which is last unless a
    device is selected on that track). Returns {"track", "device": the name it has on the chain, "at": its index}."""
    before, after = load_effect(client, track, device, pause)
    index = landed(before, after)
    name = after[index]
    if at is not None and at != index:
        index = move(client, track, index, at, pause)
    return {"track": track, "device": name, "at": index}


def _where(before: list[str], after: list[str], index: int) -> int | None:
    """Where the device that was at `index` of `before` sits in `after`, when only it moved; None when `after` is
    not `before` with that one device somewhere else."""
    if after == before:
        return index
    rest = before[:index] + before[index + 1 :]
    for k, name in enumerate(after):
        if k != index and name == before[index] and after[:k] + after[k + 1 :] == rest:
            return k
    return None


def move(client: McpTransport, track: str, index: int, to: int, pause: Callable[[float], None] = time.sleep) -> int:
    """Move the device at `index` of `track` so that it ends at index `to`; returns the index it is at afterwards.

    Live's `song.move_device(device, target, position)` puts the device before the one now at `position`, so a move
    to the right asks for `to + 1`. That reading of `position` is not confirmed on every Live version, so the chain
    is read afterwards (a call of its own), and when the device is not where it was asked to be the other reading is
    tried once. ChainError if the chain changed in a way this step did not ask for."""
    before = names(client, track)
    if not 0 <= index < len(before):
        raise ChainError(f"{track!r} has no device at index {index} (it has {len(before)})")
    to = max(0, min(len(before) - 1, to))
    if to == index:
        return index
    at = index
    for position in (to + 1, to) if to > index else (to, to + 1):
        client.run(
            f"_t = {tr(track)}\n_d = _t.devices[{at}]\n"
            f"if _d.name != {before[index]!r}:\n    raise ValueError('the chain changed')\n"
            f"song.move_device(_d, _t, {position})\nresult = 'ok'"
        )
        pause(0.1)
        now = names(client, track)
        found = _where(before, now, index)
        if found is None:
            raise ChainError(f"{track!r}: the chain is {now} after moving {before[index]!r}; it was {before}")
        at = found
        if at == to:
            break
    return at


def delete(client: McpTransport, track: str, index: int, name: str) -> bool:
    """Delete the device called `name` at `index` of `track`. False, and nothing deleted, when the device there is not
    called `name`: the chain was changed by hand since, and another device of the same name may be one the person
    put there. A device we cannot be sure of is never deleted."""
    have = names(client, track)
    if not (0 <= index < len(have) and have[index] == name):
        return False
    client.run(
        f"_t = {tr(track)}\nif _t.devices[{index}].name != {name!r}:\n    raise ValueError('the chain changed')\n"
        f"_t.delete_device({index})\nresult = 'ok'"
    )
    return True


def index_of(have: list[str], name: str, near: int) -> int | None:
    """The index of the device called `name` in a chain: `near` if that one has the name, else the one closest."""
    if 0 <= near < len(have) and have[near] == name:
        return near
    found = [k for k, n in enumerate(have) if n == name]
    return min(found, key=lambda k: abs(k - near)) if found else None
