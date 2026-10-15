"""COLDFIRE's knobs for the LOM: Live shows a plugin's parameters only once they are "configured" (at most 128 per
device, stored in the .als as each PluginDevice's ParameterList). This set's COLDFIRE instances are the VST2 build,
which has 2312 parameters in an order that differs from the VST3's 277 (pedalboard reads the VST3: names, ranges and
value labels, in pb/coldfire_params.json). So the VST2 indices are found in Live:

  uv run python scripts/industrial/coldfire.py probe     # a copy of the set: instance k shows indices 128k..128k+127
  (open the probe set in Live)
  uv run python scripts/industrial/coldfire.py names     # read every shown name back; writes coldfire_vst2.json
  uv run python scripts/industrial/coldfire.py expose    # the set itself: every COLDFIRE shows the knobs in KNOBS

Offline, on the gzipped XML, like strip.py.
"""
from __future__ import annotations

import copy
import gzip
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ops  # noqa: E402

SET = ops.SET_DIR / f"{ops.SET_NAME}.als"
PROBE = ops.SET_DIR / "INDUS_probe.als"
MAP = Path(__file__).parent / "coldfire_vst2.json"   # VST2 index by name, learned from the probe set

# the knobs that shape a distortion, by their (VST3, pedalboard) names
KNOBS = ["On/Off", "Input Volume", "Output Volume", "Mix", "Color", "Routing Balance", "Routing Band Split",
         "Distortion A Output Level", "Distortion A Dry/Wet", "Distortion A Slot Bypass",
         "Distortion A Distortion Bypass", "Distortion A Module Type", "Distortion A Drive",
         "Distortion A Pre Filter Bypass", "Distortion A Pre Filter Freq", "Distortion A Pre Filter Q",
         "Distortion A Post Filter Bypass ", "Distortion A Post Filter HP Freq", "Distortion A Post Filter LP Freq",
         "Distortion A Rectifier Center", "Distortion A Tube Profile", "Distortion A Bitcrusher Frequency",
         "Distortion B Output Level", "Distortion B Dry/Wet", "Distortion B Slot Bypass",
         "Distortion B Distortion Bypass", "Distortion B Module Type", "Distortion B Drive",
         "Distortion B Post Filter Bypass ", "Distortion B Post Filter HP Freq", "Distortion B Post Filter LP Freq",
         "Distortion B Tube Profile", "Compressor Threshold", "Compressor Ratio", "Compressor Makeup Gain",
         "Limiter Threshold", "Limiter Output Gain"]


def load(path: Path) -> ET.Element:
    return ET.fromstring(gzip.open(path).read())


def save(root: ET.Element, path: Path) -> None:
    with gzip.open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8"))


def coldfires(root: ET.Element) -> list[ET.Element]:
    out = []
    for d in root.iter("PluginDevice"):
        n = d.find(".//PlugName")
        if n is not None and "COLDFIRE" in n.get("Value", ""):
            out.append(d)
    return out


def configure(root: ET.Element, dev: ET.Element, ids: list[int], names: list[str] | None = None) -> None:
    """Make `dev` show the VST2 parameters `ids` (in order). The entries copy the device's first stored one; every
    Id the set must keep unique (automation and modulation targets) comes from the set's NextPointeeId."""
    ls = root.find("LiveSet")
    nxt = ls.find("NextPointeeId")
    pid = int(nxt.get("Value"))
    pl = dev.find("ParameterList")
    template = copy.deepcopy(pl[0])
    for c in list(pl):
        pl.remove(c)
    for k, idx in enumerate(ids):
        e = copy.deepcopy(template)
        e.set("Id", str(k))
        e.find("ParameterName").set("Value", names[k] if names else f"p{idx}")
        e.find("ParameterId").set("Value", str(idx))
        e.find("VisualIndex").set("Value", str(k))
        for tag in ("AutomationTarget", "ModulationTarget"):
            t = e.find(f"ParameterValue/{tag}")
            if t is not None:
                t.set("Id", str(pid))
                pid += 1
        pl.append(e)
    nxt.set("Value", str(pid))


def probe() -> None:
    root = load(SET)
    devs = coldfires(root)
    for k, d in enumerate(devs):
        configure(root, d, list(range(128 * k, min(128 * (k + 1), 2312))))
    save(root, PROBE)
    print(PROBE, len(devs), "instances, indices 0 ..", min(128 * len(devs), 2312) - 1)


def names() -> None:
    """With the probe set open in Live: every COLDFIRE's shown parameters, name -> VST2 index."""
    from ops import L
    got = L.run("""out = []
def walk(devs):
    for d in devs:
        if d.class_name == 'PluginDevice' and 'COLDFIRE' in d.name:
            out.append([p.name for p in list(d.parameters)[1:]])
        if d.can_have_chains:
            for c in d.chains:
                walk(c.devices)
        if hasattr(d, 'drum_pads'):
            pass
for t in list(song.tracks) + [song.master_track]:
    walk(t.devices)
result = out""")
    print(len(got), "instances shown,", [len(x) for x in got])
    return got



def state(dev: ET.Element) -> dict[str, float]:
    """The instance's saved knob values, normalised 0-1, by COLDFIRE's internal names: its VST2 chunk (the .als Buffer)
    is a Boost text archive of "<length> <name> <value>" runs."""
    b = bytes.fromhex("".join(dev.find(".//Buffer").text.split())).decode("latin1")
    out, i = {}, 0
    import re
    pat = re.compile(r"(\d+) ")
    while True:
        m = pat.search(b, i)
        if not m:
            break
        n = int(m.group(1))
        name = b[m.end():m.end() + n]
        rest = b[m.end() + n:m.end() + n + 32]
        v = re.match(r" (-?[\d.]+(?:e-?\d+)?)(?= |$)", rest)
        if v and n > 1 and name.strip() == name and not name[0].isdigit():
            try:
                out[name] = float(v.group(1))
                i = m.end() + n + v.end()
                continue
            except ValueError:
                pass
        i = m.end()
    return out


# the knobs shown to the LOM: VST2 display name -> the chunk's internal name (normalised values are the same)
SHOWN = {
    "Input Volume": "Input Volume", "Output Volume": "Output Volume", "Mix": "Mix", "Color": "Tilt EQ",
    "Distortion A Output Level": "Distortion A_Output Level", "Distortion A Dry/Wet": "Distortion A_Dry Wet",
    "Distortion A Module Type": "Distortion A_DistortionVariant_ModuleType",
    "Distortion A Drive": "Distortion A_DistortionVariant_Drive",
    "Distortion A Post Filter HP Freq": "Distortion A_Post Filter HP_Freq",
    "Distortion A Post Filter LP Freq": "Distortion A_Post Filter LP_Freq",
    "Distortion A Rectifier Center": "Distortion A_DistortionVariant_Rectifier_Center",
    "Distortion B Output Level": "Distortion B_Output Level", "Distortion B Dry/Wet": "Distortion B_Dry Wet",
    "Distortion B Module Type": "Distortion B_DistortionVariant_ModuleType",
    "Distortion B Drive": "Distortion B_DistortionVariant_Drive",
    "Distortion B Post Filter HP Freq": "Distortion B_Post Filter HP_Freq",
    "Distortion B Post Filter LP Freq": "Distortion B_Post Filter LP_Freq",
}


def expose(path: Path = SET) -> None:
    """Every COLDFIRE in the set shows the SHOWN knobs, each written with the instance's own saved value (Live takes
    a shown knob's value from the .als and sends it to the plugin, so a wrong value here would change the sound)."""
    vst2 = json.loads(MAP.read_text())
    root = load(path)
    devs = coldfires(root)
    for d in devs:
        s = state(d)
        names = [n for n in SHOWN if SHOWN[n] in s]
        configure(root, d, [vst2[n] for n in names], names)
        for e, n in zip(d.find("ParameterList"), names):
            e.find("ParameterValue/Manual").set("Value", repr(s[SHOWN[n]]))
    save(root, path)
    print(path, len(devs), "instances,", len(SHOWN), "knobs each")


if __name__ == "__main__":
    {"probe": probe, "names": names, "expose": expose}[sys.argv[1]]()
