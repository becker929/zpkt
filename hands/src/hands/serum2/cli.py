"""`hands serum2 ...`: Serum 2 patches and knobs without its window.

    hands serum2 presets [QUERY]                          factory presets matching QUERY
    hands serum2 render PRESET [--notes 69,72] [--wav F]  offline check of a preset
    hands serum2 apply SET.als TRACK --preset P [--knob NAME ...] [--mod SPEC ...] [--param NAME=RAW ...]

`apply` backs the set up (SET.als -> SET.<timestamp>.bak.als), writes the preset (plus edits) into
the track's Serum 2 and configures the knobs in encoder order, in place. Live must then reload
the set (`hands live reload`). Save Live first, or its unsaved changes are lost on reload.
--mod SPEC: "env2>Oscillator.kParamCoarsePit[0]=24" (source>Type.Param[module index]=amount).
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import time
from pathlib import Path

import typer

app = typer.Typer(help=__doc__, no_args_is_help=True)
PRESETS = "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets"
MOD_RE = re.compile(r"^(\w+)>(\w+)\.(\w+)\[(\d+)\]=(-?[\d.]+)$")


def find_preset(query: str) -> Path:
    p = Path(query).expanduser()
    if p.is_file():
        return p
    hits = sorted(f for f in glob.glob(PRESETS + "/**/*.SerumPreset", recursive=True)
                  if query.lower() in os.path.relpath(f, PRESETS).lower())
    if not hits:
        raise typer.BadParameter(f"no factory preset matches {query!r}")
    return Path(hits[0])


@app.command()
def presets(query: str = typer.Argument("", help="Substring of the preset file name.")) -> None:
    """List factory presets (category folder / name)."""
    for f in sorted(glob.glob(PRESETS + "/**/*.SerumPreset", recursive=True)):
        if query.lower() in os.path.relpath(f, PRESETS).lower():
            print(os.path.relpath(f, PRESETS))


def _patched(preset: Path, mods: list[str], params: list[str]):
    from hands.serum2 import state as st
    from hands.serum2.als import mod_dest_ids
    from hands.serum2.offline import Serum

    s = Serum()
    template, _ = s.state()
    proc = st.preset_to_processor(preset.read_bytes(), template)
    if mods:
        blob = st.decode(proc)
        ids = mod_dest_ids()
        free = [k for k in sorted(blob.data, key=lambda k: int(k[7:]) if k[7:].isdigit() else 999)
                if k.startswith("ModSlot") and "source" not in blob.data[k]]
        for spec in mods:
            m = MOD_RE.match(spec.replace(" ", ""))
            if not m:
                raise typer.BadParameter(f"--mod {spec!r}: want source>Type.Param[idx]=amount")
            src, typ, prm, idx, amt = m.groups()
            key = f"{typ}.{prm}"
            if key not in ids:
                raise typer.BadParameter(f"unknown mod destination {key} (see mod_dest_ids.json)")
            blob.data[free.pop(0)] = st.mod_slot(src, typ, prm, ids[key], float(amt), int(idx))
        proc = st.encode(blob)
    s.load(proc)
    for kv in params:
        name, raw = kv.rsplit("=", 1)
        s.set(name, float(raw))
    return s


@app.command()
def render(preset: str, notes: str = typer.Option("69,72", help="Comma-separated MIDI notes (a chord)."),
           wav: Path = typer.Option(None, help="Write the render here."),
           mod: list[str] = typer.Option([], help="Mod routing SPEC (repeatable)."),
           param: list[str] = typer.Option([], help="NAME=RAW (repeatable).")) -> None:
    """Render a preset offline and print peak / RMS / spectral centroid."""
    from hands.serum2.offline import SR, check

    path = find_preset(preset)
    s = _patched(path, mod, param)
    a = s.render(tuple((int(n), 0.0, 1.2) for n in notes.split(",")), dur=2.5)
    print(path.name, check(a))
    if wav:
        import soundfile as sf
        sf.write(wav, a.T, SR)


@app.command()
def apply(set_path: Path, track: str, preset: str = typer.Option(..., help="Factory preset name or a .SerumPreset path."),
          knob: list[str] = typer.Option([], help="Serum parameter for encoder 1, 2, ... (repeatable)."),
          mod: list[str] = typer.Option([], help="Mod routing SPEC (repeatable)."),
          param: list[str] = typer.Option([], help="NAME=RAW (repeatable).")) -> None:
    """Write a preset (+ edits, + configured knobs) into TRACK's Serum 2, after a backup."""
    from hands import als
    from hands.serum2.als import configure, find_serum, set_state

    path = find_preset(preset)
    s = _patched(path, mod, param)
    proc, ctl = s.state()
    tree = als.load(set_path)
    dev = find_serum(tree, track)
    set_state(tree, dev, proc, ctl)
    if knob:
        configure(dev, [(k, s.get(k)) for k in knob])
    backup = set_path.with_name(f"{set_path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.bak.als")
    shutil.copy2(set_path, backup)
    als.save(tree, set_path, overwrite=True)
    print(f"wrote {path.stem} into {track!r} in {set_path} (backup {backup.name}); now reload Live")
