"""The arrangement file (`arrangements/<id>.json`): the recipe each page adds its structure to, and the one parse of
each body the pages send. Pure functions: plain data in, plain data out, `Rejected` for a body the server refuses.

Who writes what (production-map.md): the arranger page owns `name, bars, regions, mutes`; the transitions page
`transitions`; mix 1 `mix`; mix 2 `mix2`; the spectral page `spectral`; the kick and spectral pages `kickFuzz`; the
mix desk (contrib/mixdesk/recipe.py) `desk`, outside this server. A save from the arranger page keeps every key it
does not own, so no later step is lost when the arrangement is edited.

The type names two halves: `Structure` (regions and transitions, with the page's name, bars and mutes) and `Sound`
(mix, mix2, spectral, kickFuzz, desk). The file does not nest them: their keys stay side by side at the top level.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any, NotRequired, TypedDict, cast

ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LOOP_FILE = re.compile(r"[a-z0-9-]{1,32}\.flac")
PAGE_KEYS = ("name", "bars", "regions", "mutes")  # what the arranger page sends and owns
MAX_BELLS = 6


class Region(TypedDict):
    """One clip on one lane: `start` is the 0-based bar, `len` bars long, entered `off` bars into the loop."""

    lane: str
    clip: str
    start: int
    len: int
    off: NotRequired[int]


class KickOption(TypedDict):
    """The kick kept on the kick or spectral page (kickfuzz.py): its loop, the kick turned to keep its loudness, and
    the match EQ's bells [(Hz, dB, Q)] if it has one."""

    loop: str
    kickTurnedDb: float
    bells: NotRequired[list[list[float]] | None]


class Structure(TypedDict):
    """The arrangement's structure: what plays where. The arranger page owns name, bars, regions and mutes; the
    transitions page `transitions`."""

    name: NotRequired[str]
    bars: NotRequired[int]
    regions: list[Region]
    mutes: NotRequired[list[str]]
    transitions: NotRequired[list[dict[str, Any]]]


class Sound(TypedDict):
    """How the arrangement sounds: mix 1 `mix`, mix 2 `mix2`, the spectral page `spectral`, the kick option
    `kickFuzz`, the mix desk's `desk`."""

    mix: NotRequired[dict[str, Any]]
    mix2: NotRequired[list[dict[str, Any]]]
    spectral: NotRequired[list[dict[str, Any]]]
    kickFuzz: NotRequired[KickOption | None]
    desk: NotRequired[dict[str, Any]]


class Arrangement(Structure, Sound):
    """The arrangement file: its structure and its sound. The two halves are named in the type only; in the file their
    keys sit side by side at the top level, with `saved` (when the arranger page last saved it)."""

    saved: NotRequired[float]


STRUCTURE_KEYS = tuple(Structure.__annotations__)  # name, bars, regions, mutes, transitions
SOUND_KEYS = tuple(Sound.__annotations__)  # mix, mix2, spectral, kickFuzz, desk


def structure(a: dict[str, Any]) -> Structure:
    """The structure half of an arrangement file: the keys of it the file holds."""
    return cast(Structure, {k: a[k] for k in STRUCTURE_KEYS if k in a})


def sound(a: dict[str, Any]) -> Sound:
    """The sound half of an arrangement file: the keys of it the file holds."""
    return cast(Sound, {k: a[k] for k in SOUND_KEYS if k in a})


class Rejected(ValueError):
    """A body the server refuses; the message is the error the page gets."""


def _check(ok: bool, error: str) -> None:
    if not ok:
        raise Rejected(error)


def parse_page_save(body: Any) -> Arrangement:
    """The arranger page's save: an object with a list of regions."""
    _check(isinstance(body, dict) and isinstance(body.get("regions"), list), "bad arrangement")
    return cast(Arrangement, body)


def merge_page_save(new: Arrangement, old: dict[str, Any] | None, now: float | None = None) -> dict[str, Any]:
    """What the file holds after a page save: the page's body, stamped `saved`, with every key of the old file that
    the page does not own and did not send (the later steps' structure, the mix desk's `desk`)."""
    kept = {k: v for k, v in (old or {}).items() if k not in PAGE_KEYS and k != "saved" and k not in new}
    return {**new, "saved": time.time() if now is None else now, **kept}


def _parse_transitions(t: Any) -> Any:
    _check(isinstance(t, list) and all(isinstance(x, dict) and "id" in x and "seam" in x for x in t), "")
    return t


def _parse_mix(t: Any) -> Any:
    _check(isinstance(t, dict) and isinstance(t.get("channels"), dict), "")
    return t


def _parse_mix2(t: Any) -> Any:
    _check(isinstance(t, list) and all(isinstance(x, dict) and "device" in x and "target" in x for x in t), "")
    return t


def _parse_spectral(t: Any) -> Any:
    _check(isinstance(t, list) and all(isinstance(x, dict) and "id" in x and "parts" in x for x in t), "")
    return t


def _parse_kick_option(t: Any) -> Any:
    """The kick option kept, or null for HW002's kick as it is."""
    if t is None:
        return None
    _check(isinstance(t, dict), "")
    _check(isinstance(t.get("loop"), str) and LOOP_FILE.fullmatch(t["loop"]) is not None, "")
    _check(isinstance(t.get("kickTurnedDb"), (int, float)), "")
    bells = t.get("bells")
    _check(
        bells is None
        or (
            isinstance(bells, list)
            and len(bells) <= MAX_BELLS
            and all(isinstance(b, list) and len(b) == 3 and all(isinstance(v, (int, float)) for v in b) for b in bells)
        ),
        "",
    )
    return t


# A later page's key -> the parse of the body it sends (PUT /api/arrangements/<id>/<key>).
LATER_KEYS: dict[str, Callable[[Any], Any]] = {
    "transitions": _parse_transitions,
    "mix": _parse_mix,
    "mix2": _parse_mix2,
    "spectral": _parse_spectral,
    "kickFuzz": _parse_kick_option,
}


def parse_later_key(key: str, body: Any) -> Any:
    """A later page's structure for `key`, or Rejected("bad <key>")."""
    try:
        return LATER_KEYS[key](body)
    except Rejected:
        raise Rejected(f"bad {key}") from None


def parse_transitions_view(body: Any) -> dict[str, Any]:
    """The transitions page's own view (the change shown, hearts, stacks): an object with `picks`."""
    _check(isinstance(body, dict) and isinstance(body.get("picks"), dict), "bad picks")
    return cast(dict[str, Any], body)


MIX2_LAST_BAR = 40


def parse_mix2_request(body: Any) -> dict[str, Any]:
    """A mix-2 batch: a target, a device, one or two parameters, a stretch of bars (1-based, inclusive, in 1-40)."""
    try:
        ok = (
            isinstance(body, dict)
            and isinstance(body.get("target"), str)
            and isinstance(body.get("device"), str)
            and isinstance(body.get("params"), list)
            and 1 <= len(body["params"]) <= 2
            and isinstance(body.get("bars"), list)
            and len(body["bars"]) == 2
            and 1 <= body["bars"][0] <= body["bars"][1] <= MIX2_LAST_BAR
        )
    except TypeError:  # bars that are not numbers
        ok = False
    _check(ok, "bad request")
    return cast(dict[str, Any], body)


def list_row(arrangement_id: str, a: dict[str, Any]) -> dict[str, Any]:
    """One arrangement in the page's list."""
    return {"id": arrangement_id, "name": a.get("name", arrangement_id), "bars": a.get("bars"), "saved": a.get("saved")}
