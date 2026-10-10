"""build_rig.py - idempotent isolated-stem bounce rig builder (Path B / LOM).

Replaces the fragile hand-copied step-5 LOM sequence from the knob-measure-map
skill with one re-runnable command. It ensures, on the currently-open Live set:
  1. a capture audio track (default name STEM_CAP) whose INPUT taps the source
     track's output, and
  2. a looping session clip in the source track's slot 0 that replays the
     source's trigger pattern (so firing it isolates the source into the tap).

It is IDEMPOTENT: existing pieces are detected and left alone; only missing
pieces are created. `--check` reports the rig state and mutates NOTHING.

Follows the LOM crash rules: write then read in SEPARATE calls, sleep between
mutating calls, re-fetch song.tracks[i] after create.

Usage:
    uv run python sweeps/build_rig.py --source "Kick (G)"            # build/repair
    uv run python sweeps/build_rig.py --source 6 --check            # report only
    uv run python sweeps/build_rig.py --source "Kick (G)" --notes auto --loop-beats 4

Prints a JSON summary: source/capture indices, notes, what was created, rig_ready.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MCP = os.path.expanduser(
    os.environ.get("ABLETON_MCP",
                   "~/.agents/skills/ableton-live-control/scripts/live_mcp.py"))


class RigError(Exception):
    pass


def mcp(code: str, mcp_path: str = DEFAULT_MCP):
    """Run one LOM snippet via live_mcp.py --json and return the parsed result."""
    proc = subprocess.run(
        [sys.executable, mcp_path, "--json", "--retries", "2", code],
        capture_output=True, text=True, timeout=40)
    if proc.returncode != 0:
        raise RigError(f"MCP call failed: {proc.stderr.strip() or proc.stdout.strip()}")
    out = proc.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RigError(f"MCP returned non-JSON: {out!r}")


def resolve_source(source: str, mcp_path: str) -> tuple[int, str, list[str]]:
    names = mcp("result=[t.name for t in song.tracks]", mcp_path)
    if source.lstrip("-").isdigit():
        idx = int(source)
        if not (0 <= idx < len(names)):
            raise RigError(f"source index {idx} out of range (0..{len(names)-1})")
        return idx, names[idx], names
    matches = [i for i, n in enumerate(names) if n == source]
    if not matches:
        raise RigError(f"no track named {source!r}. Tracks: {names}")
    return matches[0], source, names


def discover_notes(src: int, mcp_path: str) -> list[int]:
    code = (f"c=song.tracks[{src}].arrangement_clips[0]; "
            "ns=list(c.get_notes_extended(0,128,0,8)); "
            "result=sorted({n.pitch for n in ns})")
    try:
        pitches = mcp(code, mcp_path)
    except RigError:
        pitches = []
    return pitches or [36]  # sensible default: standard kick pad


def find_capture(cap_name: str, names: list[str]) -> int | None:
    hits = [i for i, n in enumerate(names) if n == cap_name]
    return hits[0] if hits else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="source track name or index (the instrument to tap)")
    p.add_argument("--source-input", default=None, help="input routing display name (default: source track name)")
    p.add_argument("--capture-name", default="STEM_CAP")
    p.add_argument("--notes", default="auto", help="'auto' (discover) or comma list e.g. 2,4")
    p.add_argument("--loop-beats", type=int, default=4)
    p.add_argument("--clip-name", default="STEM_LOOP")
    p.add_argument("--check", action="store_true", help="report rig state; mutate nothing")
    p.add_argument("--mcp", default=DEFAULT_MCP)
    args = p.parse_args()

    if not Path(args.mcp).exists():
        raise SystemExit(f"live_mcp.py not found at {args.mcp} (set --mcp or $ABLETON_MCP)")

    src, src_name, names = resolve_source(args.source, args.mcp)
    src_input = args.source_input or src_name
    created: list[str] = []

    # --- state: capture track present? ---
    cap = find_capture(args.capture_name, names)

    # --- state: session clip in source slot 0? ---
    has_clip = mcp(f"cs=song.tracks[{src}].clip_slots[0]; result=bool(cs.has_clip)", args.mcp)

    # --- notes ---
    if args.notes == "auto":
        notes = discover_notes(src, args.mcp)
    else:
        notes = [int(x) for x in args.notes.split(",") if x.strip()]

    if args.check:
        cap_in = None
        if cap is not None:
            cap_in = mcp(f"result=song.tracks[{cap}].input_routing_type.display_name", args.mcp)
        print(json.dumps({
            "mode": "check",
            "source_track": src, "source_name": src_name,
            "capture_track": cap, "capture_input": cap_in,
            "session_clip_slot0": has_clip,
            "notes": notes,
            "rig_ready": cap is not None and bool(has_clip) and cap_in == src_input,
        }, indent=2))
        return

    # --- create capture track if missing ---
    if cap is None:
        mcp("song.create_audio_track(-1); result='created'", args.mcp)
        time.sleep(0.4)
        info = mcp(
            "i=len(song.tracks)-1; tr=song.tracks[i]; tr.name=%r; "
            "rt=next(r for r in tr.available_input_routing_types if r.display_name==%r); "
            "tr.input_routing_type=rt; "
            "result={'idx':i,'in':tr.input_routing_type.display_name}"
            % (args.capture_name, src_input),
            args.mcp)
        cap = info["idx"]
        created.append(f"capture_track[{cap}]={args.capture_name}<-{info['in']}")
        time.sleep(0.3)

    # --- create session clip if missing ---
    if not has_clip:
        mcp(f"song.tracks[{src}].clip_slots[0].create_clip({float(args.loop_beats)}); result='clip'", args.mcp)
        time.sleep(0.4)
        notes_expr = (
            "notes=[MidiNoteSpecification(pitch=p, start_time=float(b), duration=0.25, velocity=100) "
            f"for b in range({args.loop_beats}) for p in {tuple(notes)!r}]; "
            f"c=song.tracks[{src}].clip_slots[0].clip; c.name={args.clip_name!r}; "
            "c.add_new_notes(tuple(notes)); c.looping=1; result='notes'")
        mcp(notes_expr, args.mcp)
        created.append(f"session_clip[src={src}].slot0={args.clip_name} 4-on-{args.loop_beats} notes={notes}")
        time.sleep(0.3)

    cap_in = mcp(f"result=song.tracks[{cap}].input_routing_type.display_name", args.mcp)
    rig_ready = cap is not None and cap_in == src_input
    print(json.dumps({
        "mode": "build",
        "source_track": src, "source_name": src_name,
        "capture_track": cap, "capture_input": cap_in,
        "notes": notes, "created": created, "rig_ready": rig_ready,
    }, indent=2))


if __name__ == "__main__":
    main()
