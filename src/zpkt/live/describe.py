"""What a control needs to know about a value of the mix, by its state key: kind, range, unit, steps, default, shown
stops and what it shows now. Also what is selected in Live. The one interface's pages are built from these, so a page
never carries a range or a unit of its own.

    hands live describe "Kick bus/desk EQ/1 Gain A" "Kick bus/volume"
    hands live selection

One LOM call describes up to 32 keys. A key the set lacks comes back as its reason, never as a guess.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from zpkt.live import inlive
from zpkt.live.state import ShownRaw
from zpkt.live.transport import McpTransport

CHUNK = 32  # keys per call
Kind = Literal["switch", "choice", "continuous"]


class Description(TypedDict):
    key: str
    name: str  # the LOM parameter's name; "volume", "pan", "mute", "solo" for the mixer's
    kind: Kind
    min: float
    max: float
    default: float | None
    steps: int | None  # for a switch (2) or a list
    items: list[str]  # a switch's or list's shown texts, lowest first
    unit: str  # of what it shows now: "dB", "Hz", "kHz", "%", "" for none
    stops: list[ShownRaw]  # shown texts spread over a continuous range, lowest first
    now: ShownRaw
    enabled: bool
    plain: bool  # continuous, but what Live shows is not a number: a control shows the raw value


def brief(d: Description) -> dict[str, Any]:
    """The description without its `stops` (the long part: each continuous value carries a spread of shown texts)."""
    return {k: v for k, v in d.items() if k != "stops"}


class Selection(TypedDict):
    track: str | None
    device: str | None
    param: str | None
    key: str | None  # the selected parameter's state key, when a key can name it


_DESCRIBE = """import json
out, missing = {{}}, {{}}
for key in {keys!r}:
    try:
        found = find_value(song, key)
    except (LookupError, ValueError) as exc:
        missing[key] = str(exc)
        continue
    if isinstance(found, tuple):
        on = bool(getattr(found[0], found[1]))
        d = {{'name': found[1], 'kind': 'switch', 'min': 0.0, 'max': 1.0, 'default': 0.0, 'steps': 2,
             'items': ['False', 'True'], 'unit': '', 'stops': [], 'now': [str(on), on], 'enabled': True,
             'plain': False}}
    else:
        d = describe(found, {stops})
    d['key'] = key
    out[key] = d
result = json.dumps({{'found': out, 'missing': missing}})"""

_SELECTION = "import json\nresult = json.dumps(selection_key(song))"


class Missing(LookupError):
    """Keys the open set does not have: `.missing` is {key: why}."""

    def __init__(self, missing: dict[str, str]) -> None:
        super().__init__("; ".join(missing.values()))
        self.missing = missing


def _typed(d: dict[str, Any]) -> Description:
    rest = d["key"].partition("/")[2]
    if "/" not in rest:
        d["name"] = rest  # the mixer's values by their name in the key, not Live's "Track Volume" or "A-Send"
    d["now"] = ShownRaw(d["now"])
    d["stops"] = [ShownRaw(s) for s in d["stops"]]
    return d  # type: ignore[return-value]  # the shape inlive.shown.describe makes


def look(client: McpTransport, keys: list[str], stops: int = 5) -> tuple[dict[str, Description], dict[str, str]]:
    """(descriptions by key, why by key for those the set lacks). Never raises for a missing key."""
    found: dict[str, Description] = {}
    missing: dict[str, str] = {}
    unique = list(dict.fromkeys(keys))
    for i in range(0, len(unique), CHUNK):
        code = inlive.with_source(_DESCRIBE.format(keys=unique[i : i + CHUNK], stops=int(stops)), "shown", "find")
        reply = json.loads(client.run(code))
        found.update({k: _typed(d) for k, d in reply["found"].items()})
        missing.update(reply["missing"])
    return found, missing


def describe(client: McpTransport, keys: list[str], stops: int = 5) -> dict[str, Description]:
    """Each key's description; Missing if the open set lacks any of them."""
    found, missing = look(client, keys, stops)
    if missing:
        raise Missing(missing)
    return found


def selection(client: McpTransport) -> Selection:
    """The track, device and parameter selected in Live, as keys spell them (None where nothing is selected)."""
    return json.loads(client.run(inlive.with_source(_SELECTION, "find")))
