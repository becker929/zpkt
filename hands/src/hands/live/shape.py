"""The shape of the JSON handed to `hands panel` and `hands song`, checked before Live is touched.

An agent writes these specs, and a weak one writes them slightly wrong: a track name where a list of
names goes, "124" for 124, null for a key it did not mean to give, a key that does not exist ("volume").
Each used to end in a Python error from deep inside, or, worse, in a key silently ignored and a render
that looked like success. `clean` returns the spec put right where the meaning is plain (a lone name
becomes a list of one, a numeric string a number, null is dropped) and otherwise raises a PanelError
that names the key, shows the shape it takes and lists the keys there are.

A schema is: NUM, Between(lo, hi), TEXT, FLAG, ANY, [item], {key: schema} (only these keys), Open(schema) (any keys),
Row(a, b, ...) or Either(a, b, ...).
"""

from __future__ import annotations

import difflib
import json
import math
from typing import Any

from hands.live.panel import PanelError

NUM, TEXT, FLAG, ANY = "a number", "text", "true or false", "anything"


class Open:
    """An object with any keys, each value of one schema."""

    def __init__(self, item: Any) -> None:
        self.item = item


class Between:
    """A number from lo to hi (Live's own limits, or what a real-time render can take)."""

    def __init__(self, lo: float, hi: float, what: str = "") -> None:
        self.lo, self.hi, self.what = lo, hi, what


class Row:
    """A list with a place for each thing ([pitch, start, length, velocity]); the last `optional` may be left off."""

    def __init__(self, *items: Any, optional: int = 0, says: str = "") -> None:
        self.items, self.optional, self.says = items, optional, says


class Either:
    def __init__(self, *options: Any) -> None:
        self.options = options


TEMPO = Between(20, 999, "beats per minute, as in Live")
TAIL = Between(0, 64, "beats of ring-out after the last note")
VALUE = Either(NUM, TEXT, FLAG)  # a parameter's value: raw, as Live shows it ("800 Hz"), or a switch
CONTROL = Either(TEXT, {"param": TEXT, "label": TEXT})
NOTE = Row(
    Either(NUM, TEXT),
    Between(0, 1024),
    Between(0.001, 1024),
    Between(0, 127),
    optional=1,
    says="[pitch, start beat, length in beats, velocity]",
)
RIFF = {
    "notes": [NOTE],
    "seq": TEXT,
    "chords": TEXT,
    "rhythm": TEXT,
    "every": Between(0.01, 16),
    "gate": Between(0.01, 1),
    "velocity": Between(1, 127),
    "beats": Between(1, 1024),
    "pattern_beats": Between(0.25, 1024),
}
INSTRUMENT = {
    "name": TEXT,
    "title": TEXT,
    "instrument": TEXT,
    "sound": TEXT,
    "params": Open(VALUE),
    "controls": [CONTROL],
    "tempo": TEMPO,
    "tail": TAIL,
    **RIFF,
}
INSTRUMENT_CHANGE = {k: v for k, v in INSTRUMENT.items() if k not in ("name", "instrument")}
MIX = {
    "name": TEXT,
    "title": TEXT,
    "bars": [NUM],
    "faders": [TEXT],
    "pans": [TEXT],
    "song": TEXT,
    "devices": [{"track": TEXT, "device": TEXT, "params": Open(VALUE), "controls": [CONTROL]}],
}
MIX_CHANGE = {"values": Open(VALUE), "bars": [NUM]}
AXES = Open(
    Either({"from": Either(NUM, TEXT), "to": Either(NUM, TEXT), "steps": Between(2, 8), "values": [VALUE]}, [VALUE])
)
SONG = {
    "name": TEXT,
    "tempo": TEMPO,
    "tail": TAIL,
    "sections": [{"name": TEXT, "bars": Between(1, 512), "parts": [TEXT]}],
}

EXAMPLES = {
    "faders": '["Kick bus", "Hats bus"]',
    "pans": '["Kick bus"]',
    "bars": "[17, 8] (first bar, how many)",
    "devices": '[{"track": "Kick bus", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}]',
    "params": '{"Filter Freq": "600 Hz", "Filter Res": "40%"}',
    "controls": '["Filter Freq", {"param": "Filter Res", "label": "Res"}]',
    "notes": '[["A1", 0, 0.5, 110], ["C2", 1, 0.5, 100]]',
    "seq": '"A B C D"',
    "sections": '[{"name": "intro", "bars": 8, "parts": ["bass-panel"]}]',
    "parts": '["bass-panel"]',
    "values": '{"Kick bus": "-3 dB"} for a change, [-6, -3, 0] in a grid',
    "tempo": "124",
    "steps": "4",
}


# Keys agents reach for that do not exist, by a key of the schema they were tried on: where the thing really goes.
WRONG = [
    (
        {"volume", "volumes", "level", "levels", "gain", "db", "values", "value"},
        "faders",
        ' A level is set once the panel is made: hands panel apply NAME --spec \'{"values": {"Kick bus": "-3 dB"}}\'.',
    ),
    (
        {"eq", "effects", "effect", "fx", "plugins", "plugin", "saturator", "compressor", "device"},
        "faders",
        ' An effect goes in "devices": [{"track": "Kick bus", "device": "EQ Eight", "params": {...}, "controls": [...]}].',
    ),
    ({"tracks", "track", "buses", "bus", "channels"}, "faders", ' The tracks to balance go in "faders" (and "pans").'),
    ({"tempo", "bpm"}, "faders", " A mix panel plays the set at the set's own tempo."),
    (
        {"faders", "pans", "devices", "track", "tracks"},
        "values",
        " To change which tracks or devices a mix panel has, make it again: hands panel make --replace --spec '{...}'.",
    ),
    (
        {"bars", "faders", "devices"},
        "instrument",
        ' A panel over tracks already in the set (a mix panel) has "bars" and no "instrument" or "sound".',
    ),
    (
        {"volume", "level", "gain"},
        "instrument",
        ' An instrument\'s level is one of its parameters: "params": {"Volume": "-12 dB"}.',
    ),
    ({"bpm"}, "instrument", ' It is "tempo".'),
    (
        {"notes", "seq", "chords", "instrument", "sound"},
        "sections",
        ' A song is made of panels that exist: "sections": [{"name", "bars", "parts": [panel names]}].',
    ),
]


def _short(v: Any) -> str:
    text = json.dumps(v, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def _says(schema: Any) -> str:
    if isinstance(schema, str):
        return schema
    if isinstance(schema, Row):
        return schema.says
    if isinstance(schema, Between):
        return f"a number from {schema.lo:g} to {schema.hi:g}" + (f" ({schema.what})" if schema.what else "")
    if isinstance(schema, list):
        return f"a list of {_says(schema[0])}" if schema[0] != ANY else "a list"
    if isinstance(schema, Either):
        return " or ".join(dict.fromkeys(_says(o) for o in schema.options))
    return "an object {...}"


def _bad(path: str, schema: Any, got: Any) -> PanelError:
    key = path.rsplit(".", 1)[-1].split("[")[0].strip('"')
    example = f", for example {EXAMPLES[key]}" if key in EXAMPLES else ""
    return PanelError(f"{path} must be {_says(schema)}{example}; got {_short(got)}")


def clean(value: Any, schema: Any, path: str) -> Any:
    """`value` in the shape of `schema`, put right where its meaning is plain. PanelError otherwise."""
    if schema == ANY:
        return value
    if schema == NUM:
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                raise _bad(path, schema, value) from None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(value) > 1e9
        ):
            raise _bad(path, schema, value)
        return value
    if isinstance(schema, Between):
        try:
            n = clean(value, NUM, path)
        except PanelError:
            raise _bad(path, schema, value) from None
        if not schema.lo <= n <= schema.hi:
            raise _bad(path, schema, value)
        return n
    if schema == TEXT:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return f"{value:g}"
        if not isinstance(value, str) or "\x00" in value or len(value) > 2000:
            raise _bad(path, schema, value if not isinstance(value, str) else value[:40])
        return value
    if schema == FLAG:
        if not isinstance(value, bool):
            raise _bad(path, schema, value)
        return value
    if isinstance(schema, Either):
        for option in schema.options:
            try:
                if option == TEXT and not isinstance(value, str):
                    continue  # a number is a number here, not text
                return clean(value, option, path)
            except PanelError:
                continue
        raise _bad(path, schema, value)
    if isinstance(schema, Row):
        if not isinstance(value, (list, tuple)) or not len(schema.items) - schema.optional <= len(value) <= len(
            schema.items
        ):
            raise _bad(path, schema, value)
        try:
            return [clean(v, item, path) for v, item in zip(value, schema.items)]
        except PanelError:
            raise _bad(path, schema, value) from None
    if isinstance(schema, list):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and schema[0] == TEXT:
            value = [value]  # one name where a list of names goes
        if not isinstance(value, list):
            raise _bad(path, schema, value)
        if len(value) > 512:
            raise PanelError(f"{path} has {len(value)} items; that is more than a panel can use")
        return [clean(v, schema[0], f"{path}[{i}]") for i, v in enumerate(value)]
    if not isinstance(value, dict):
        raise _bad(path, schema, value)
    if isinstance(schema, Open):
        if any(not isinstance(k, str) or not k.strip() for k in value):
            raise PanelError(f"{path} has an empty name")
        return {k: clean(v, schema.item, f'{path}["{k[:40]}"]') for k, v in value.items() if v is not None}
    out = {}
    for k, v in value.items():
        if k not in schema:
            near = difflib.get_close_matches(str(k), list(schema), n=1, cutoff=0.6)
            hint = next((h for keys, need, h in WRONG if str(k).lower() in keys and need in schema), "")
            raise PanelError(
                f'{path} has no key "{str(k)[:40]}"'
                + (f' (did you mean "{near[0]}"?)' if near and not hint else "")
                + f"; its keys are: {', '.join(schema)}."
                + hint
            )
        if v is not None:  # null means "not given"
            out[k] = clean(v, schema[k], f'"{k}"' if path in ("the spec", "--spec") else f"{path}.{k}")
    return out


def state(value: Any) -> dict:
    """The page's Surface state, or just its values: {"values": {control id: number or switch}} or {id: ...}.
    Anything else in it (a deck's side, the page's own keys) is left for the caller to skip."""
    if value is None:
        return {"values": {}}
    if not isinstance(value, dict):
        raise PanelError(f'--state must be an object: {{"values": {{"control id": 0.5}}}}; got {_short(value)}')
    values = value.get("values", value)
    if not isinstance(values, dict):
        raise PanelError(f'--state "values" must be an object {{"control id": 0.5}}; got {_short(values)}')
    return {
        "values": {
            k: v
            for k, v in values.items()
            if isinstance(k, str)
            and isinstance(v, (bool, int, float, str))
            and not (isinstance(v, float) and not math.isfinite(v))
        }
    }
