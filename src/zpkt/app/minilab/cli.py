"""`zpkt app midi ...`: the MiniLab's tools. They are for a person at the rig; no test runs them on hardware.

    zpkt app midi profile                 print the controller profile and what is still unverified (opens nothing)
    zpkt app midi learn CONTROL           listen on the MiniLab's port for one message and print it as a profile entry
    zpkt app midi latency [--seconds N]   start the app with the MIDI adapter and a probe; turn knobs for N seconds,
                                          then read the knob-to-Live timings (the gate before the pager retires)

`latency` talks to the real Live and the real MiniLab: run it on the rig, with Live's MiniLab 3 control surface set to
None and the old desk stopped. The tests run the same code on fakes (`run_latency`, `learn_message`).
"""

from __future__ import annotations

import argparse
import json
import queue
import time
from collections.abc import Callable, Sequence
from typing import Any

from zpkt.app.adapters import AdapterError, AppContext
from zpkt.app.minilab.latency import LatencyProbe, format_summary
from zpkt.app.minilab.ports import MidiPort, open_port
from zpkt.app.minilab.profile import Event, Message, Profile, load_profile, profile_path

LEARN_WAIT_S = 20.0
LATENCY_SECONDS = 30.0


def describe_profile(profile: Profile) -> str:
    """The profile as lines: each control, its message, where it came from; then what is not known."""
    lines = [f"{profile.device}: {len(profile.controls)} controls, none verified at the hardware ({profile_path()})"]
    for c in profile.controls:
        m = c.message
        if m.first is not None:
            what = f"{m.type} ch {m.channel} {m.first}-{m.last}"
        elif m.type == "pitchbend":
            what = f"pitchbend ch {m.channel}"
        else:
            what = f"{m.type} ch {m.channel} " + ("number not known yet" if m.number is None else str(m.number))
        lines.append(f"  {c.name:<18} {what:<28} {c.basis}")
    unlearned = profile.unlearned()
    if unlearned:
        lines.append(f"not known yet (ignored until learned): {', '.join(unlearned)}. Try: zpkt app midi learn NAME")
    return "\n".join(lines)


def message_of(event: Event) -> Message:
    """The profile entry for an event: what `learn` proposes."""
    return Message(event.kind, event.channel, None if event.kind == "pitchbend" else event.number)


def learn_message(port: MidiPort, wait_s: float = LEARN_WAIT_S) -> Event | None:
    """Listen on the port for one message; None if none comes in `wait_s` seconds."""
    got: queue.Queue[Event] = queue.Queue()
    port.start(got.put)
    try:
        return got.get(timeout=wait_s)
    except queue.Empty:
        return None
    finally:
        port.close()


def run_latency(
    context: AppContext,
    port: MidiPort,
    seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    profile: Profile | None = None,
) -> dict[str, dict[str, float]]:
    """Run the MIDI adapter with a probe for `seconds` and return the summary. The adapter's own start and stop; the
    app's other threads (the pager's reports, the supervisor) are the caller's."""
    from zpkt.app.adapters.midi import MidiAdapter

    probe = LatencyProbe()
    adapter = MidiAdapter(context, port=port, profile=profile, probe=probe)
    adapter.start()
    try:
        sleep(seconds)
    finally:
        adapter.stop()
    return probe.report()


def _learn(args: argparse.Namespace) -> int:
    profile = load_profile()
    names = [c.name for c in profile.controls]
    if args.control not in names:
        print(f"no control {args.control!r}; the controls are {', '.join(names)}")
        return 2
    port = open_port(profile, args.port)
    print(f"Press {args.control} on the MiniLab ({port.name}) ...", flush=True)
    event = learn_message(port, args.seconds)
    if event is None:
        print("Nothing came in. Check the cable, and that Live's MiniLab 3 control surface is set to None.")
        return 1
    print(f'Put this under the control "{args.control}" in {profile_path()}, as its "message":')
    m = message_of(event)
    print(json.dumps({"type": m.type, "channel": m.channel, "number": m.number}))
    return 0


def _latency(args: argparse.Namespace) -> int:
    from zpkt.app.adapters import create
    from zpkt.app.desk import Desk, Settings

    profile = load_profile()
    desk = Desk(Settings.from_env())
    context = AppContext(desk.bus, desk, desk.settings)
    (web,) = create(["web"], context)
    web.start()  # the desk's threads: the pager's reports are what the echo is measured against
    print(f"Turn knobs on the MiniLab for {args.seconds:g} seconds ...", flush=True)
    try:
        result = run_latency(context, open_port(profile, args.port), args.seconds, profile=profile)
    finally:
        web.stop()
    print(format_summary(result))
    return 0


def _profile(args: argparse.Namespace) -> int:
    print(describe_profile(load_profile()))
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="zpkt app midi", description="The MiniLab's tools (see zpkt.app.minilab.cli).")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("profile", help="print the controller profile and what is unverified").set_defaults(run=_profile)
    learn = sub.add_parser("learn", help="listen for one message and print it as a profile entry")
    learn.add_argument("control")
    learn.add_argument("--port", help="the port's name (default: ZPKT_MINILAB_PORT, or the profile's match)")
    learn.add_argument("--seconds", type=float, default=LEARN_WAIT_S)
    learn.set_defaults(run=_learn)
    latency = sub.add_parser("latency", help="measure knob-to-Live timings on the rig")
    latency.add_argument("--port", help="the port's name")
    latency.add_argument("--seconds", type=float, default=LATENCY_SECONDS)
    latency.set_defaults(run=_latency)
    return p.parse_args(list(argv))


def main(argv: Sequence[str]) -> int:
    args: Any = parse_args(argv)
    try:
        return int(args.run(args))
    except AdapterError as exc:
        print(f"zpkt app midi: {exc}")
        return 2
