"""Put a Serum 2 state and configured (knob) parameters into a .als, offline.

Configured parameters are the first <PluginFloatParameter> slots of the device's <ParameterList>
(Live pre-allocates 128 with ParameterId -1). Each gets ParameterName, ParameterId (the index in
Live's `device.get_parameter_names()`, = param_names.json), VisualIndex (0..7 = the MiniLab
encoders' order) and Manual (normalized 0..1). Verified on Live 12.4.16 / Serum 2.1.5.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from xml.etree import ElementTree as ET

from hands import als


def param_names() -> list[str]:
    return json.loads(resources.files("hands.serum2").joinpath("param_names.json").read_text())


def mod_dest_ids() -> dict[str, int]:
    return json.loads(resources.files("hands.serum2").joinpath("mod_dest_ids.json").read_text())


def serum_devices(track: ET.Element) -> list[ET.Element]:
    return [d for d in track.iter("PluginDevice")
            if any(n.get("Value") == "Serum 2" for n in d.iter("Name"))]


def find_serum(tree: ET.ElementTree, track_name: str) -> ET.Element:
    devs = serum_devices(als.find_track(tree, track_name))
    if not devs:
        raise LookupError(f"no Serum 2 on track {track_name!r}")
    return devs[0]


def _req(el: ET.Element, path: str) -> ET.Element:
    found = el.find(path)
    if found is None:
        raise ValueError(f"Serum 2 device has no {path}")
    return found


def _hex_text(data: bytes, indent: str) -> str:
    h = data.hex().upper()
    return "\n" + "\n".join(indent + h[i:i + 80] for i in range(0, len(h), 80)) + "\n" + indent[:-1]


def get_state(dev: ET.Element) -> tuple[bytes, bytes]:
    p, c = _req(dev, ".//ProcessorState"), _req(dev, ".//ControllerState")
    return (bytes.fromhex(re.sub(r"\s+", "", p.text or "")), bytes.fromhex(re.sub(r"\s+", "", c.text or "")))


def set_state(tree: ET.ElementTree, dev: ET.Element, processor: bytes, controller: bytes | None = None) -> None:
    root = tree.getroot()
    assert root is not None
    for tag, data in (("ProcessorState", processor), ("ControllerState", controller)):
        if data is None:
            continue
        el = _req(dev, ".//" + tag)
        el.text = _hex_text(data, "\t" * (als.depth(root, el) + 1))


def configure(dev: ET.Element, knobs: list[tuple[str, float]]) -> None:
    """knobs: [(Serum parameter name, normalized value)], in encoder order (max 128)."""
    names = param_names()
    slots = list(_req(dev, ".//ParameterList"))
    floats = [s for s in slots if s.tag == "PluginFloatParameter"]
    if len(knobs) > len(floats):
        raise ValueError("too many knobs")
    for i, (name, value) in enumerate(knobs):
        pid = names.index(name)  # ValueError = not a Serum 2 parameter name
        slot = floats[i]
        _req(slot, "ParameterName").set("Value", name)
        _req(slot, "ParameterId").set("Value", str(pid))
        _req(slot, "VisualIndex").set("Value", str(i))
        _req(slot, "ParameterValue/Manual").set("Value", f"{min(1.0, max(0.0, value)):.7f}")
    for slot in floats[len(knobs):]:  # un-configure leftovers from an earlier knob set
        if _req(slot, "ParameterId").get("Value") != "-1":
            _req(slot, "ParameterName").set("Value", "")
            _req(slot, "ParameterId").set("Value", "-1")
            _req(slot, "VisualIndex").set("Value", "1073741823")
