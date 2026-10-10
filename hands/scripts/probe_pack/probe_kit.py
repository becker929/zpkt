"""Horizontal probe kit: one Live load + one Main export renders P variants of a section.

  template  build once: copy a set, keep [lead] + one section, Duplicate Time to P patterns, save.
  batch     per batch, offline: add devices from a donor set and step any device parameter per
            pattern, written straight into a copy of the template (.als XML, see als_probe.py).
  render    load the batch set, export Main once, slice it into one WAV per pattern.

Measured on HW002 (FINDINGS.md): ~4 s per 20-bar probe at P=16, Live memory flat. Every Live
step is guarded (pp.check) and stops on anything unexpected. Usage from ~/Desktop/zpkt/hands:

  uv run python scripts/probe_pack/probe_kit.py template KIT SRC_SET KEEP_START KEEP_END P [LEAD]
  uv run python scripts/probe_pack/probe_kit.py render  BATCH_SET KIT
"""
import json
import os
import sys
import time

import soundfile as sf

import pp
from hands import als as X
from pp import A, TO, log

KITS = pp.DATA + "kits/"


def _end():
    return A.r("result = song.last_event_time")


def _clips_after(beat):
    return A.r(f"result = sum(len([c for c in t.arrangement_clips if c.end_time > {beat}]) "
               f"for t in song.tracks if not t.is_foldable)")


def _delete(start, length):
    """Edit > Delete Time, verified by the song end moving by `length` (within one beat: an
    automation breakpoint just past the content can be absorbed)."""
    before = _end()
    TO.select(start, length)
    if not A.menu("Edit", "Delete Time", tries=6):
        raise pp.Guard("Edit > Delete Time stayed disabled")
    time.sleep(1.0)
    moved = before - _end()
    if abs(moved - length) > 1.0 + 1e-6:
        raise pp.Guard(f"Delete Time {start}+{length}: song end moved {moved}")


def _duplicate(start, length):
    TO.select(start, length)
    if not A.menu("Edit", "Duplicate Time", tries=6):
        raise pp.Guard("Edit > Duplicate Time stayed disabled")
    time.sleep(1.0)


def template(kit, src, keep_start, keep_end, P, lead=8.0):
    """Kit set = [0, lead) of `src` + [keep_start, keep_end) of `src`, repeated P times (P a power of 2)."""
    if P & (P - 1):
        raise ValueError("P must be a power of two (built by doubling)")
    name = f"HW002_121_pp_kit_{kit}"
    pat = keep_end - keep_start
    pp.check("kit:start")
    pp.copy_set(src, name)
    pp.prepare_switch()
    t = time.time(); pp.open_set(name); log("kit_load", time.time() - t, kit=kit)
    pp.check("kit:loaded", expect_front=name)
    end = _end()
    if end > keep_end + 1.0:
        _delete(keep_end, end - keep_end)
        pp.check("kit:trim_tail", expect_front=name)
    if keep_start > lead:
        _delete(lead, keep_start - lead)
        pp.check("kit:trim_gap", expect_front=name)
    end = _end()
    if not (lead + pat <= end <= lead + pat + 2.0):
        raise pp.Guard(f"kit: after trims the set ends at {end}, expected about {lead + pat}")
    n = 1
    while n < P:
        before = _clips_after(lead)
        t = time.time(); _duplicate(lead, n * pat); log("kit_duplicate", time.time() - t, kit=kit, to_P=2 * n)
        n *= 2
        pp.check(f"kit:dup{n}", expect_front=name)
        end, after = _end(), _clips_after(lead)
        if abs(end - (lead + n * pat)) > 1e-6 or after != 2 * before:
            raise pp.Guard(f"kit: duplicating to {n}: end {end} (want {lead + n * pat}), clips {after} (want {2 * before})")
    if not pp.save(name):
        raise pp.Guard("kit: save did not write the file")
    pp.check("kit:saved", expect_front=name)
    os.makedirs(KITS, exist_ok=True)
    meta = {"kit": kit, "set": name, "src": src, "keep": [keep_start, keep_end], "lead": lead, "pattern_beats": pat, "P": P}
    json.dump(meta, open(KITS + kit + ".json", "w"), indent=1)
    return meta


def resolve(tree, track, dev, param):
    """(track element, device element, parameter path relative to the device).

    dev: "Mixer" (the track mixer: volume, pan, sends), ("plugin", PlugName) for a VST/AU device,
    or (device_tag, index) for a Live device (index among devices with that tag; -1 = last).
    param: an XML path for Live devices ("Bands.3/ParameterA/Gain"); a plugin parameter's
    display name ("Drive") for plugins, which resolves to its ParameterValue element."""
    tr = X.find_track(tree, track)
    if dev == "Mixer":
        return tr, tr.find("./DeviceChain/Mixer"), param
    if isinstance(dev, str):                       # older call style: a tag, last such device
        dev = (dev, -1)
    if dev[0] == "plugin":
        plugs = [d for d in X.devices(tr) if d.tag == "PluginDevice"
                 and any(e.get("Value") == dev[1] for e in d.find("./PluginDesc").iter() if e.tag in ("PlugName", "Name"))]
        if len(plugs) != 1:
            raise KeyError(f"{track}: {len(plugs)} plugins named {dev[1]!r}")
        params = plugs[0].findall("./ParameterList/PluginFloatParameter")
        idx = [i for i, p in enumerate(params, 1) if p.find("./ParameterName").get("Value") == param]
        if len(idx) != 1:
            raise KeyError(f"{track}/{dev[1]}: {len(idx)} parameters named {param!r}")
        return tr, plugs[0], f"ParameterList/PluginFloatParameter[{idx[0]}]/ParameterValue"
    return tr, X.find_device(tr, dev[0], dev[1]), param


def current_value(tree, track, dev, param):
    """The parameter's knob value in the set (float, or bool for switches)."""
    _, d, path = resolve(tree, track, dev, param)
    v = d.find(path).find("Manual").get("Value")
    return v == "true" if v in ("true", "false") else float(v)


def write_batch(kit, tag, devices, steps):
    """Offline. devices: [(track, donor_set, donor_track, device_tag)] appended to `track`.
    steps: [(track, device_tag or "Mixer", param_xml_path, [value per pattern])]. Returns the batch set name."""
    meta = json.load(open(KITS + kit + ".json"))
    tree = X.load(os.path.join(pp.PROJ, meta["set"] + ".als"))
    for track, donor_set, donor_track, tag_ in devices:
        donor = X.find_device(X.find_track(X.load(os.path.join(pp.PROJ, donor_set + ".als")), donor_track), tag_)
        X.add_device_from_donor(tree, X.find_track(tree, track), donor)
    for track, dev, param, values in steps:
        if len(values) != meta["P"]:
            raise ValueError(f"{len(values)} values for {meta['P']} patterns")
        st = [(0.0 if j == 0 else meta["lead"] + j * meta["pattern_beats"], v) for j, v in enumerate(values)]
        tr, d, path = resolve(tree, track, dev, param)
        X.set_steps(tree, tr, d, path, st)
    name = f"HW002_121_pp_x_{kit}_{tag}"
    path = os.path.join(pp.PROJ, name + ".als")
    X.save(tree, path, overwrite=True)
    problems = X.check(path).problems
    if problems:
        raise pp.Guard(f"als check failed: {problems}")
    return name


def render(batch_set, kit, out_dir):
    """Guarded load + one Main export + slice into pattern_XX.wav. Returns the manifest."""
    meta = json.load(open(KITS + kit + ".json"))
    lead, pat, P = meta["lead"], meta["pattern_beats"], meta["P"]
    pp.check("render:start")
    pp.prepare_switch()
    t = time.time(); pp.open_set(batch_set); t_load = time.time() - t
    pp.check("render:loaded", expect_front=batch_set)
    os.makedirs(out_dir, exist_ok=True)
    t = time.time(); pp.export(os.path.join(out_dir, "all.wav"), 0.0, lead + P * pat, "Main"); t_export = time.time() - t
    pp.check("render:exported", expect_front=batch_set)
    x, sr = sf.read(os.path.join(out_dir, "all.wav"), always_2d=True, dtype="float32")
    spb = 60.0 / A.r("result = song.tempo")
    files = []
    for k in range(P):
        a, b = int((lead + k * pat) * spb * sr), int((lead + (k + 1) * pat) * spb * sr)
        f = os.path.join(out_dir, f"pattern_{k:02d}.wav")
        sf.write(f, x[a:b], sr, subtype="FLOAT")
        files.append(f)
    man = {"batch_set": batch_set, "kit": meta, "load_s": round(t_load, 2), "export_s": round(t_export, 2),
           "files": files, "seconds_per_probe": round((t_load + t_export) / P, 2)}
    json.dump(man, open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
    log("kit_render", t_load + t_export, kit=kit, P=P, load=round(t_load, 2), export=round(t_export, 2))
    return man


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "template":
        kit, src, ks, ke, P = sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), int(sys.argv[6])
        print(json.dumps(template(kit, src, ks, ke, P, float(sys.argv[7]) if len(sys.argv) > 7 else 8.0)))
    elif cmd == "render":
        print(json.dumps(render(sys.argv[2], sys.argv[3], pp.DATA + "kit_out/" + sys.argv[2])))
