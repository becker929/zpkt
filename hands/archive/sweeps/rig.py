"""One-command rig setup / teardown for a sweep track (Path B / LOM over MCP).

Every sweep needs the same dance: turn the target device ON, turn the other
audio effects OFF so the knob is the only variable, run the sweep, then put the
track back exactly as it was. Doing that by hand is how you lose a rig.

Three subcommands:

    snapshot      READ-ONLY. Record every device on a track: index, name,
                  class_name, its On parameter, and a watched-parameter list.
                  Writes `snapshots/<name>.json`.
    solo-device   Target device On=1, every other audio effect On=0. Writes a
                  `<name>.pre.json` snapshot FIRST, so it is always restorable.
                  The track's instrument (device type 1) is kept ON by default,
                  otherwise the track would bounce silence.
    restore       Write a snapshot's On values + watched params back, then
                  RE-READ and verify every one. Prints a pass/fail table and
                  exits nonzero on any mismatch.

LOM crash rules honoured throughout: one device per call, <= ~20 parameters per
call, writes and read-backs are always separate calls, no long loops in a call.
This script never saves the Live set.

Examples:
    # capture the restore target (do this before you touch anything)
    uv run python sweeps/rig.py snapshot --track 6 --name snts_kick_devices

    # isolate StandardCLIP for a clipper sweep
    uv run python sweeps/rig.py solo-device --track 6 --device 6 \\
        --name snts_kick_clip_solo

    # put it back and prove it
    uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_clip_solo.pre.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hands.transport import LiveMcpTransport, McpResult  # noqa: E402

SCHEMA = "hands.rig.snapshot/1"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# Live names the on/off switch "Device On" (native + most VSTs) or "On".
ON_PARAM_NAMES = ("Device On", "On")

# Live's Device.type: 1 = instrument, 2 = audio effect, 4 = midi effect.
INSTRUMENT_TYPE = 1

# Watched parameters we care about per track, as "<device_index>:<param_name>".
# These are the knobs the SNTS kick sweeps actually move, so a snapshot of
# track 6 is a complete restore target for Phases 3-5.
DEFAULT_WATCH: dict[int, tuple[str, ...]] = {
    6: ("1:Style", "1:Drive", "3:Attack", "3:Sustain", "6:Clipping"),
}


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def _run(t: LiveMcpTransport, code: str) -> McpResult:
    r = t.execute(code)
    if r.status != "ok":
        raise RuntimeError(f"MCP error running code:\n{code}\n-> {r.error}")
    return r


def connect(host: str, port: int) -> LiveMcpTransport:
    t = LiveMcpTransport(host=host, port=port)
    ping = t.execute("result = 1 + 1")
    if ping.status != "ok" or ping.result != 2:
        raise SystemExit(f"MCP bridge not reachable on {host}:{port} ({ping.error})")
    return t


def parse_watch(items: list[str] | None, track: int) -> dict[int, list[str]]:
    """Turn `["1:Drive", "6:Clipping"]` into `{1: ["Drive"], 6: ["Clipping"]}`."""
    raw = items if items is not None else list(DEFAULT_WATCH.get(track, ()))
    out: dict[int, list[str]] = {}
    for item in raw:
        if ":" not in item:
            raise SystemExit(f"--watch wants '<device_index>:<param_name>', got {item!r}")
        idx_txt, name = item.split(":", 1)
        try:
            idx = int(idx_txt)
        except ValueError:
            raise SystemExit(f"--watch device index is not an int: {item!r}") from None
        out.setdefault(idx, []).append(name)
    return out


# ---------------------------------------------------------------------------
# Reading state
# ---------------------------------------------------------------------------

def track_header(t: LiveMcpTransport, track: int) -> dict[str, Any]:
    """Track name plus the (index, name, class_name, type) of every device."""
    r = _run(t, (
        f"tr = song.tracks[{track}]\n"
        f"result = {{'track_name': tr.name,\n"
        f"          'devices': [(i, d.name, d.class_name, d.type)"
        f" for i, d in enumerate(tr.devices)]}}"
    ))
    return r.result


def read_device(
    t: LiveMcpTransport, track: int, index: int, watch_names: list[str],
) -> dict[str, Any]:
    """One call per device: its On parameter plus any watched parameters.

    The On parameter is found by name match against `ON_PARAM_NAMES`; `next()`
    takes the lowest matching index, which is `parameters[0]` in practice for
    both Ableton natives and VSTs. A device with no matching name gets
    `on_param: null` and is left alone by solo/restore.
    """
    r = _run(t, (
        f"d = song.tracks[{track}].devices[{index}]\n"
        f"_on_names = {list(ON_PARAM_NAMES)!r}\n"
        f"_watch = {watch_names!r}\n"
        f"_on = next(((i, p.name, p.value) for i, p in enumerate(d.parameters)"
        f" if p.name in _on_names), None)\n"
        f"_w = [(i, p.name, p.value) for i, p in enumerate(d.parameters)"
        f" if p.name in _watch]\n"
        f"result = {{'name': d.name, 'class_name': d.class_name, 'type': d.type,\n"
        f"          'n_parameters': len(d.parameters), 'on': _on, 'watched': _w}}"
    ))
    raw = r.result
    on = raw.get("on")
    return {
        "index": index,
        "name": raw["name"],
        "class_name": raw["class_name"],
        "type": raw["type"],
        "is_instrument": raw["type"] == INSTRUMENT_TYPE,
        "n_parameters": raw["n_parameters"],
        "on_param": None if not on else {
            "index": on[0], "name": on[1], "value": on[2],
        },
        "watched": [
            {"index": w[0], "name": w[1], "value": w[2]} for w in (raw.get("watched") or [])
        ],
    }


def take_snapshot(
    t: LiveMcpTransport, track: int, watch: dict[int, list[str]],
) -> dict[str, Any]:
    """Read the whole track, one MCP call per device. READ-ONLY."""
    head = track_header(t, track)
    devices = [
        read_device(t, track, i, watch.get(i, []))
        for i, _name, _cls, _type in head["devices"]
    ]
    return {
        "schema": SCHEMA,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "track_index": track,
        "track_name": head["track_name"],
        "watch": {str(k): v for k, v in sorted(watch.items())},
        "devices": devices,
    }


def snapshot_path(name: str, suffix: str = "") -> Path:
    """`snapshots/<name><suffix>.json`, accepting a bare name or a real path."""
    if name.endswith(".json") or "/" in name:
        p = Path(name)
        if suffix:
            p = p.with_name(p.name.removesuffix(".json") + suffix + ".json")
        return p
    return SNAPSHOT_DIR / f"{name}{suffix}.json"


def write_snapshot(snap: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2) + "\n")
    return path


def print_snapshot(snap: dict[str, Any]) -> None:
    print(f"track {snap['track_index']} {snap['track_name']!r} "
          f"({len(snap['devices'])} devices)")
    print(f"  {'idx':>3}  {'on':>4}  {'name':<24} {'class_name':<22} watched")
    for d in snap["devices"]:
        on = d["on_param"]
        on_txt = "n/a" if on is None else f"{on['value']:.0f}"
        tag = "  [instrument]" if d["is_instrument"] else ""
        watched = ", ".join(f"{w['name']}={w['value']:.6g}" for w in d["watched"]) or "-"
        print(f"  {d['index']:>3}  {on_txt:>4}  {d['name']:<24} "
              f"{d['class_name']:<22} {watched}{tag}")


# ---------------------------------------------------------------------------
# Writing state
# ---------------------------------------------------------------------------

def write_device_params(
    t: LiveMcpTransport, track: int, index: int, assignments: list[tuple[str, float]],
) -> None:
    """Set named parameters on one device. WRITE ONLY -- never read here (LOM Rule 1)."""
    if not assignments:
        return
    lines = [f"d = song.tracks[{track}].devices[{index}]", "_missing = []"]
    for name, value in assignments:
        lines.append(f"_p = next((p for p in d.parameters if p.name == {name!r}), None)")
        lines.append(f"if _p is None: _missing.append({name!r})")
        lines.append(f"else: _p.value = {float(value)!r}")
    lines.append("result = _missing or 'set'")
    missing = _run(t, "\n".join(lines)).result
    if isinstance(missing, list) and missing:
        raise RuntimeError(
            f"track {track} devices[{index}]: parameters not found: {missing}"
        )


# ---------------------------------------------------------------------------
# Subcommand: snapshot
# ---------------------------------------------------------------------------

def cmd_snapshot(args: argparse.Namespace) -> int:
    t = connect(args.host, args.port)
    watch = parse_watch(args.watch, args.track)
    snap = take_snapshot(t, args.track, watch)
    path = write_snapshot(snap, snapshot_path(args.name))
    print_snapshot(snap)
    print(f"\nWrote {path}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: solo-device
# ---------------------------------------------------------------------------

def cmd_solo_device(args: argparse.Namespace) -> int:
    t = connect(args.host, args.port)
    watch = parse_watch(args.watch, args.track)

    # 1. Always snapshot BEFORE writing, so this is reversible no matter what.
    pre = take_snapshot(t, args.track, watch)
    pre_path = write_snapshot(pre, snapshot_path(args.name, ".pre"))
    print(f"Wrote restore point: {pre_path}\n")

    by_index = {d["index"]: d for d in pre["devices"]}
    if args.device not in by_index:
        raise SystemExit(
            f"track {args.track} has no devices[{args.device}] "
            f"(indices 0..{len(pre['devices']) - 1})"
        )
    target = by_index[args.device]
    if target["on_param"] is None:
        raise SystemExit(
            f"devices[{args.device}] {target['name']!r} has no "
            f"{'/'.join(ON_PARAM_NAMES)} parameter; cannot solo it"
        )

    keep = set(args.keep or [])
    if not args.no_keep_instrument:
        keep |= {d["index"] for d in pre["devices"] if d["is_instrument"]}
    keep.add(args.device)

    # 2. Write: one device per call, no read-back in the same call.
    plan: list[tuple[int, float, str]] = []
    for d in pre["devices"]:
        if d["on_param"] is None:
            continue
        if d["index"] == args.device:
            plan.append((d["index"], 1.0, "target -> ON"))
        elif d["index"] in keep:
            plan.append((d["index"], d["on_param"]["value"], "kept as-is"))
        else:
            plan.append((d["index"], 0.0, "-> OFF"))

    for index, value, why in plan:
        if value == by_index[index]["on_param"]["value"]:
            print(f"  [{index:>2}] {by_index[index]['name']:<24} {why} (already {value:.0f})")
            continue
        write_device_params(t, args.track, index, [(by_index[index]["on_param"]["name"], value)])
        print(f"  [{index:>2}] {by_index[index]['name']:<24} {why}")

    # 3. Verify in SEPARATE read calls.
    print()
    wanted = {index: value for index, value, _why in plan}
    post = take_snapshot(t, args.track, watch)
    ok = report_verification(post, wanted, args.tol)
    post_path = write_snapshot(post, snapshot_path(args.name, ".post"))
    print(f"\nWrote resulting state: {post_path}")
    print(f"Undo with: uv run python sweeps/rig.py restore --from {pre_path}")
    return 0 if ok else 1


def report_verification(
    post: dict[str, Any], wanted: dict[int, float], tol: float,
) -> bool:
    """Print an On-value pass/fail table for a just-written state."""
    print(f"  {'idx':>3}  {'device':<24} {'want':>6} {'got':>6}  status")
    ok = True
    for d in post["devices"]:
        if d["index"] not in wanted:
            continue
        got = d["on_param"]["value"] if d["on_param"] else float("nan")
        want = wanted[d["index"]]
        good = abs(got - want) <= tol
        ok &= good
        print(f"  {d['index']:>3}  {d['name']:<24} {want:>6.3f} {got:>6.3f}  "
              f"{'PASS' if good else 'FAIL'}")
    print("verify:", "PASS" if ok else "FAIL")
    return ok


# ---------------------------------------------------------------------------
# Subcommand: restore
# ---------------------------------------------------------------------------

def cmd_restore(args: argparse.Namespace) -> int:
    snap = json.loads(Path(args.from_path).read_text())
    if snap.get("schema") != SCHEMA:
        raise SystemExit(f"not a {SCHEMA} snapshot: {args.from_path}")
    track = snap["track_index"]
    t = connect(args.host, args.port)

    live_head = track_header(t, track)
    if live_head["track_name"] != snap["track_name"]:
        raise SystemExit(
            f"track {track} is now {live_head['track_name']!r} but the snapshot "
            f"says {snap['track_name']!r}; refusing to restore the wrong track"
        )
    if len(live_head["devices"]) != len(snap["devices"]):
        raise SystemExit(
            f"track {track} now has {len(live_head['devices'])} devices but the "
            f"snapshot has {len(snap['devices'])}; refusing to restore"
        )

    print(f"Restoring track {track} {snap['track_name']!r} from {args.from_path}")
    print(f"  (snapshot taken {snap['timestamp_utc']})\n")

    # 1. Write, one device per call.
    for d in snap["devices"]:
        assignments: list[tuple[str, float]] = []
        if d["on_param"] is not None:
            assignments.append((d["on_param"]["name"], d["on_param"]["value"]))
        assignments += [(w["name"], w["value"]) for w in d["watched"]]
        if not assignments:
            continue
        if args.dry_run:
            print(f"  DRY [{d['index']:>2}] {d['name']:<24} "
                  f"{', '.join(f'{n}={v:.6g}' for n, v in assignments)}")
            continue
        write_device_params(t, track, d["index"], assignments)
        print(f"  wrote [{d['index']:>2}] {d['name']:<24} "
              f"{', '.join(f'{n}={v:.6g}' for n, v in assignments)}")
    if args.dry_run:
        print("\ndry run: nothing written, nothing verified")
        return 0

    # 2. Re-read everything and verify, in separate calls.
    watch = {int(k): v for k, v in (snap.get("watch") or {}).items()}
    post = take_snapshot(t, track, watch)
    post_by_index = {d["index"]: d for d in post["devices"]}

    print(f"\n  {'idx':>3}  {'device':<24} {'param':<12} {'want':>10} {'got':>10}  status")
    ok = True
    for d in snap["devices"]:
        live = post_by_index.get(d["index"])
        checks: list[tuple[str, float]] = []
        if d["on_param"] is not None:
            checks.append((d["on_param"]["name"], d["on_param"]["value"]))
        checks += [(w["name"], w["value"]) for w in d["watched"]]
        for name, want in checks:
            got = _live_value(live, name)
            good = got is not None and abs(got - want) <= args.tol
            ok &= good
            got_txt = "MISSING" if got is None else f"{got:>10.6f}"
            print(f"  {d['index']:>3}  {d['name']:<24} {name:<12} {want:>10.6f} "
                  f"{got_txt:>10}  {'PASS' if good else 'FAIL'}")
    print(f"\nrestore verify: {'PASS' if ok else 'FAIL'} (tolerance {args.tol})")
    return 0 if ok else 1


def _live_value(device: dict[str, Any] | None, name: str) -> float | None:
    if device is None:
        return None
    on = device.get("on_param")
    if on and on["name"] == name:
        return float(on["value"])
    for w in device.get("watched", []):
        if w["name"] == name:
            return float(w["value"])
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=16619)
    p.add_argument("--tol", type=float, default=1e-4,
                   help="Read-back tolerance when verifying a write.")
    sub = p.add_subparsers(dest="cmd", required=True)

    watch_help = ("Watched parameter as '<device_index>:<param_name>', repeatable. "
                  "Default: the track's entry in DEFAULT_WATCH (track 6: the SNTS "
                  "kick sweep knobs).")

    s = sub.add_parser("snapshot", help="READ-ONLY: record a track's device state.")
    s.add_argument("--track", type=int, default=6)
    s.add_argument("--name", default="snts_kick_devices",
                   help="Snapshot name (written to sweeps/snapshots/<name>.json) or a path.")
    s.add_argument("--watch", action="append", help=watch_help)
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("solo-device", help="Target device ON, other effects OFF.")
    s.add_argument("--track", type=int, default=6)
    s.add_argument("--device", type=int, required=True, help="Device index to isolate.")
    s.add_argument("--name", default="rig_solo",
                   help="Base name; writes <name>.pre.json (restore point) and <name>.post.json.")
    s.add_argument("--watch", action="append", help=watch_help)
    s.add_argument("--keep", type=int, action="append",
                   help="Device index to leave untouched, repeatable.")
    s.add_argument("--no-keep-instrument", action="store_true",
                   help="Also switch the track's instrument off (this bounces silence).")
    s.set_defaults(func=cmd_solo_device)

    s = sub.add_parser("restore", help="Write a snapshot back and verify by read-back.")
    s.add_argument("--from", dest="from_path", required=True, help="Path to a snapshot JSON.")
    s.add_argument("--dry-run", action="store_true", help="Print the writes, do nothing.")
    s.set_defaults(func=cmd_restore)

    args = p.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
