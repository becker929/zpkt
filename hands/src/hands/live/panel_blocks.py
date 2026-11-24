"""What `hands panel` prints for Zpkt web: the zpkt-surface spec of a panel, and the facts line and fenced blocks
(~/zpkt-web/lib/panels.mjs reads them: panelOutput). Pure functions over a panel's file."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:34] or "c"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    taken.add(out)
    return out


def _num(v: float) -> float | int:
    x = float(f"{v:.6g}")
    return int(x) if x == int(x) else x


def surface(panel: dict[str, Any], ab: tuple[str, str] | None = None) -> dict[str, Any]:
    """The zpkt-surface spec for a panel as it now stands; with `ab`, a before/after deck of two renders."""
    controls = []
    for c in panel["controls"]:
        v = panel["values"].get(c["param"], c["min"])
        if c["kind"] == "toggle":
            controls.append(
                {
                    "kind": "toggle",
                    "id": c["id"],
                    "label": c["label"],
                    "value": v > (c["min"] + c["max"]) / 2,
                    "midiSlot": c["midiSlot"],
                }
            )
            continue
        k = {
            "kind": "fader" if c["kind"] == "fader" else "knob",
            "id": c["id"],
            "label": c["label"],
            "min": _num(c["min"]),
            "max": _num(c["max"]),
            "value": _num(v),
        }
        if c.get("step"):
            k["step"] = c["step"]
        if c.get("display"):
            k["display"] = c["display"]
        controls.append({**k, "midiSlot": c["midiSlot"]})
    if ab:

        def side(label: str, src: str) -> dict[str, Any]:
            return {"label": label, "src": src, "bpm": _num(panel["tempo"]), "downbeatMs": 0}

        controls.append(
            {
                "kind": "ab",
                "id": "ab",
                "label": "Before / after",
                "a": side("before", ab[0]),
                "b": side("after", ab[1]),
                "loop": {"startBar": 1, "bars": max(1, min(64, int(panel["beats"] // 4)))},
                "quantize": "bar",
            }
        )
    note = (
        f"bars {panel['bars'][0]}-{panel['bars'][0] + panel['bars'][1] - 1} at {panel['tempo']:g} BPM · v{panel['version']}"
        if panel.get("kind") == "mix"
        else f"{panel['device']} · {panel['beats']:g} beats at {panel['tempo']:g} BPM · v{panel['version']}"
    )
    return {"title": panel.get("title") or panel["name"], "note": note, "panel": panel["name"], "controls": controls}


def _shown_path(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p.resolve())


def blocks(
    panel: dict[str, Any], result: dict[str, Any], warnings: list[str], ab: tuple[str, str] | None = None
) -> str:
    """What the command prints: one line of facts, then the two blocks to paste into the answer as they are."""
    spec = surface(panel, ab)
    head, *rows = [
        json.dumps({k: v for k, v in spec.items() if k != "controls"}, ensure_ascii=False)[:-1] + ', "controls": [',
        *[" " + json.dumps(c, ensure_ascii=False) for c in spec["controls"]],
    ]
    body = head + "\n" + ",\n".join(rows) + "\n]}"
    level = f"peak {result['peak_dbfs']:g} dBFS, RMS {result['rms_dbfs']:g} dBFS, {result['seconds']:g} s"
    what = (
        "mix of " + ", ".join(dict.fromkeys(c["track"] for c in panel["controls"]))
        if panel.get("kind") == "mix"
        else f"{panel['device']} on track {panel['track']!r}"
    )
    lines = [f"panel {panel['name']} v{panel['version']}: {what}, {level}"]
    if result["peak_dbfs"] < -60:
        lines.append(
            "WARNING: the render is silent. Check the instrument's level, the notes' range and Live's audio output."
        )
    lines += [f"warning: {w}" for w in warnings]
    lines += [
        "Paste both blocks into your answer as they are:",
        "",
        "```audio",
        panel["renders"][-1],
        "```",
        "",
        "```zpkt-surface",
        body,
        "```",
        "",
        f"When the user's Surface state comes back: hands panel apply {panel['name']} --state '<that JSON>'. "
        f'Several versions to compare at once: hands panel grid {panel["name"]} --axes \'{{"{panel["controls"][0]["id"] if panel["controls"] else "id"}": {{"steps": 4}}}}\'',
    ]
    return "\n".join(lines)
