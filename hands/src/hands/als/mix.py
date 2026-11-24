"""The mix a saved set holds, read offline in the shape of hands.live.state (`hands als mix`).

Values are the file's own numbers (marked "units": "als"), so a state read here compares with another read here, not
with a state taken from Live.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from hands.als.file import devices, load, track_name

SILENT = 0.0003162277571  # Live's fader and send floor (-70 dB), shown as -inf dB


def _db(v: float) -> str:
    import math

    return "-inf dB" if v <= SILENT * 1.0001 else f"{20 * math.log10(v) + 0.0:.2f} dB".replace("-0.00", "0.00")


def _manual(el: ET.Element | None) -> float | None:
    m = el.find("Manual") if el is not None else None
    if m is None:
        return None
    v = m.get("Value")
    if v in ("true", "false"):
        return 1.0 if v == "true" else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _device_name(d: ET.Element) -> str:
    u = d.find("UserName")
    return u.get("Value") if u is not None and u.get("Value") else d.tag


def _device_params(d: ET.Element) -> dict[str, list]:
    """Every parameter with a Manual value, keyed by its path of XML tags inside the device (racks' inner
    devices included), as [shown, raw]. These are the file's units and names, not the LOM's."""
    out: dict[str, list] = {}

    def walk(el: ET.Element, path: str) -> None:
        for c in el:
            if c.tag in ("AutomationTarget", "ModulationTarget", "MidiControllerRange", "ArrangerAutomation"):
                continue
            here = f"{path}/{c.tag}" if path else c.tag
            v = _manual(c)
            if v is not None:
                out[here] = [str(v), v]
            elif len(c):
                walk(c, here)

    walk(d, "")
    return out


def mix_state(path: str | os.PathLike) -> dict:
    """The mix a saved set holds, in the shape of hands.live.state (so state.diff and summarize work on it):
    each track's volume and sends (shown in dB), pan, mute (its Speaker off), and every device's parameters.
    Values are the file's own (a fader's raw value is its gain, not the LOM's 0..1), so compare a file with
    a file; to compare with Live, take a state in Live instead."""
    tree = load(path)
    ls = tree.getroot().find("LiveSet")
    tracks = [t for t in ls.find("Tracks")]
    rets = [track_name(t) for t in tracks if t.tag == "ReturnTrack"]
    main = ls.find("MainTrack") if ls.find("MainTrack") is not None else ls.find("MasterTrack")
    out: dict = {"file": os.fspath(path), "returns": rets, "units": "als", "tracks": {}}
    for t in tracks + ([main] if main is not None else []):
        name = "Main" if t is main else track_name(t)
        m = t.find("DeviceChain/Mixer")
        vol, pan, on = _manual(m.find("Volume")), _manual(m.find("Pan")), _manual(m.find("Speaker"))
        mix: dict = {"volume": [_db(vol), vol], "pan": [f"{pan:+.2f}", pan]}
        if t is not main:
            mix["mute"] = [str(on == 0.0), on == 0.0]
            holders = m.findall("Sends/TrackSendHolder")
            mix["sends"] = {
                r: [_db(v), v]
                for r, h in zip(rets, holders, strict=False)
                if (v := _manual(h.find("Send"))) is not None
            }
        devs = [{"name": _device_name(d), "class": d.tag, "params": _device_params(d)} for d in devices(t)]
        out["tracks"][name] = {"mixer": mix, "devices": devs}
    return out


def mix_lines(state: dict) -> list[str]:
    """One line per track of a mix state: volume, pan, MUTED, the sends that are not off, the devices (off ones
    marked), as `hands als mix` prints them."""
    lines = []
    for name, t in state["tracks"].items():
        m = t["mixer"]
        sends = {r: v[0] for r, v in m.get("sends", {}).items() if not v[0].startswith("-inf")}
        devs = ", ".join(d["name"] + ("" if d["params"].get("On", [0, 1.0])[1] else " (off)") for d in t["devices"])
        muted = "  MUTED" if m.get("mute", [0, False])[1] else ""
        lines.append(
            f"{name:24s} {m['volume'][0]:>10s} pan {m['pan'][0]:>5s}{muted}"
            f"{'  sends ' + str(sends) if sends else ''}{'  | ' + devs if devs else ''}"
        )
    return lines
