#!/usr/bin/env python3
"""
Sweep a plugin parameter OUTSIDE the DAW and render each step, with pedalboard.

Why this exists: the Live API hides most VST parameters (LFOTool shows only
on/off), Live renders in real time, and Live needs a person awake at a Mac.
pedalboard hosts the same VST3 or AU plugin in Python, exposes every
parameter, renders faster than real time, and can hand back the plugin's raw
state so a setting found here can be loaded in Live. Native Ableton devices
(Drum Rack, EQ Eight, Roar, Compressor) still need Live; everything that is a
plugin does not.

    python3 lab/plugin_sweep.py list  --plugin "/Library/Audio/Plug-Ins/VST3/LFOTool.vst3"
    python3 lab/plugin_sweep.py sweep --plugin <path-or-builtin> --param <name> \\
        --values 0 0.25 0.5 0.75 1 --input stems/hw002/03__rumble__lfotool-off.wav \\
        --job rumble_lfotool --out out/plugin_sweeps/
    python3 lab/plugin_sweep.py state --plugin <path> --load-state some.state --dump

Outputs follow the sweep convention: <job>__<param>__<value>.wav plus a
.params.json sidecar with every parameter's value at that step, and a .state
file holding the plugin's raw state bytes for round-tripping. Built-in names
(Compressor, Distortion, LowpassFilter, HighpassFilter, Gain, Reverb) are
accepted for --plugin so the harness can be tested where no VSTs exist.
"""
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf
import pedalboard as pb

BUILTIN = {n: getattr(pb, n) for n in ("Compressor", "Distortion", "LowpassFilter", "HighpassFilter", "Gain", "Reverb", "Limiter") if hasattr(pb, n)}


def open_plugin(spec, plugin_name=None):
    """A path loads a VST3/AU; a bare name loads a built-in for testing."""
    if spec in BUILTIN:
        return BUILTIN[spec](), "builtin"
    p = Path(spec).expanduser()
    if not p.exists():
        sys.exit(f"plugin not found: {spec}")
    plug = pb.load_plugin(str(p), plugin_name=plugin_name) if plugin_name else pb.load_plugin(str(p))
    return plug, "external"


def param_names(plug, kind):
    if kind == "external":
        return sorted(plug.parameters.keys())
    return sorted(k for k in dir(plug) if not k.startswith("_") and k not in ("is_effect", "is_instrument")
                  and isinstance(getattr(type(plug), k, None), property))


def get_param(plug, kind, name):
    return plug.parameters[name].raw_value if kind == "external" else getattr(plug, name)


def set_param(plug, kind, name, value):
    if kind == "external":
        plug.parameters[name].raw_value = float(value)      # 0..1 normalised, the same scale Live shows
    else:
        setattr(plug, name, float(value))


def snapshot(plug, kind):
    out = {}
    for n in param_names(plug, kind):
        try:
            v = plug.parameters[n] if kind == "external" else getattr(plug, n)
            out[n] = dict(raw=float(v.raw_value), text=str(v)) if kind == "external" else float(v)
        except Exception as e:  # noqa: BLE001
            out[n] = f"unreadable: {e}"
    return out


def cmd_list(a):
    plug, kind = open_plugin(a.plugin, a.plugin_name)
    print(json.dumps(dict(plugin=a.plugin, kind=kind, name=getattr(plug, "name", a.plugin),
                          parameters=snapshot(plug, kind)), indent=1))


def cmd_sweep(a):
    plug, kind = open_plugin(a.plugin, a.plugin_name)
    if a.load_state:
        plug.raw_state = Path(a.load_state).read_bytes()
    names = param_names(plug, kind)
    if a.param not in names:
        sys.exit(f"no parameter {a.param!r}; have: {names}")
    y, sr = sf.read(a.input, dtype="float32", always_2d=True)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in a.values:
        set_param(plug, kind, a.param, v)
        t0 = time.time()
        rendered = plug(y.T, sr, reset=True).T          # pedalboard wants (channels, samples)
        dt = time.time() - t0
        tag = ("%g" % v)
        stem = f"{a.job}__{a.param}__{tag}"
        sf.write(out / f"{stem}.wav", rendered, sr)
        side = dict(job=a.job, plugin=a.plugin, kind=kind, param=a.param, requested_value=v,
                    true_value=float(get_param(plug, kind, a.param)), parameters=snapshot(plug, kind),
                    input=str(a.input), sample_rate=sr, render_seconds=round(dt, 2),
                    realtime_factor=round((len(y) / sr) / dt, 1) if dt > 0 else None)
        if kind == "external":
            (out / f"{stem}.state").write_bytes(plug.raw_state)
            side["state_file"] = f"{stem}.state"
        (out / f"{stem}.params.json").write_text(json.dumps(side, indent=1))
        rows.append(dict(value=v, true=side["true_value"], seconds=side["render_seconds"], x_realtime=side["realtime_factor"]))
        print(f"  {stem}: rendered in {dt:.2f}s ({side['realtime_factor']}x realtime)")
    (out / f"{a.job}__{a.param}.sweep.json").write_text(json.dumps(dict(job=a.job, plugin=a.plugin, param=a.param, steps=rows), indent=1))
    print(f"wrote {len(rows)} steps to {out}")


def cmd_state(a):
    plug, kind = open_plugin(a.plugin, a.plugin_name)
    if kind != "external":
        sys.exit("state round-trip needs a real plugin")
    if a.load_state:
        plug.raw_state = Path(a.load_state).read_bytes()
    if a.load_preset:
        plug.load_preset(a.load_preset)
    if a.save_state:
        Path(a.save_state).write_bytes(plug.raw_state); print(f"saved {len(plug.raw_state)} bytes to {a.save_state}")
    if a.dump:
        print(json.dumps(snapshot(plug, kind), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "sweep", "state"):
        s = sub.add_parser(name)
        s.add_argument("--plugin", required=True, help="path to a .vst3/.component, or a built-in name for testing")
        s.add_argument("--plugin-name", default=None, help="for bundles that contain several plugins")
        s.add_argument("--load-state", default=None, help="raw state bytes to load before doing anything")
    sub.choices["sweep"].add_argument("--param", required=True)
    sub.choices["sweep"].add_argument("--values", required=True, type=float, nargs="+")
    sub.choices["sweep"].add_argument("--input", required=True)
    sub.choices["sweep"].add_argument("--job", required=True)
    sub.choices["sweep"].add_argument("--out", default="out/plugin_sweeps")
    sub.choices["state"].add_argument("--load-preset", default=None, help=".vstpreset to load")
    sub.choices["state"].add_argument("--save-state", default=None)
    sub.choices["state"].add_argument("--dump", action="store_true")
    a = ap.parse_args()
    {"list": cmd_list, "sweep": cmd_sweep, "state": cmd_state}[a.cmd](a)


if __name__ == "__main__":
    main()
