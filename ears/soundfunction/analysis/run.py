"""CLI entry point.

    python3 -m analysis.run hits   <dir_or_files...> -o out/hits.csv
    python3 -m analysis.run tracks <dir_or_files...> -o out/tracks.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from .signal_features import describe_file
from .context_features import describe_track

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac"}
SWEEP_RE = re.compile(r"^(?P<sound>[^_]+(?:_[^_]+)*)__(?P<param>[^_]+(?:_[^_]+)*)__(?P<value>[^_]+)$")


def collect_audio_files(paths):
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*") if x.suffix.lower() in AUDIO_EXTS))
        elif p.is_file():
            out.append(p)
        else:
            print(f"[run] warning: path not found: {p}", file=sys.stderr)
    return out


def parse_sweep_name(path: Path):
    m = SWEEP_RE.match(path.stem)
    if not m:
        return {"sound": "", "param": "", "value": ""}
    return m.groupdict()


def cmd_hits(args):
    files = collect_audio_files(args.paths)
    rows, fail = [], 0
    for i, f in enumerate(files, 1):
        print(f"[hits] {i}/{len(files)} {f}", file=sys.stderr)
        try:
            feats = describe_file(str(f))
        except Exception as e:
            print(f"[hits] FAILED {f}: {e}", file=sys.stderr)
            fail += 1
            continue
        meta = parse_sweep_name(f)
        rows.append({"file": str(f), **meta, **feats})

    if not rows:
        print("[hits] no rows produced", file=sys.stderr)
        return

    fieldnames = ["file", "sound", "param", "value"] + \
        sorted({k for r in rows for k in r if k not in ("file", "sound", "param", "value")})
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[hits] wrote {len(rows)} rows ({fail} failed) -> {out_path}", file=sys.stderr)


def cmd_tracks(args):
    files = collect_audio_files(args.paths)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entries, fail = [], 0
    for i, f in enumerate(files, 1):
        print(f"[tracks] {i}/{len(files)} {f}", file=sys.stderr)
        npy_path = out_path.parent / f"{f.stem}.bars.npy"
        try:
            entry = describe_track(str(f), npy_path=str(npy_path))
        except Exception as e:
            print(f"[tracks] FAILED {f}: {e}", file=sys.stderr)
            fail += 1
            continue
        entries.append(entry)

    with open(out_path, "w") as fh:
        json.dump(entries, fh, indent=2)
    print(f"[tracks] wrote {len(entries)} entries ({fail} failed) -> {out_path}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="analysis.run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_hits = sub.add_parser("hits", help="extract per-hit features")
    p_hits.add_argument("paths", nargs="+")
    p_hits.add_argument("-o", "--output", required=True)
    p_hits.set_defaults(func=cmd_hits)

    p_tracks = sub.add_parser("tracks", help="extract per-track context features")
    p_tracks.add_argument("paths", nargs="+")
    p_tracks.add_argument("-o", "--output", required=True)
    p_tracks.set_defaults(func=cmd_tracks)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
