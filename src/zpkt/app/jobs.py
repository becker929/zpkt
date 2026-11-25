"""The jobs other programs ask of Live through the app: run some code, open a set, render, set the tempo, and so on.

The API adapter (and the `zpkt` command, the booth, the demo) submit these as Commands with `who` of agent, booth,
demo or cli. Each handler uses the app's one connection, so the job runs queued and under the lock. The web page is
`you` and may not ask for them: running code in Live is for callers that hold the API's token.

A job that names a set (`expect_set`) is refused with 409 when Live has another open. Opening a set is the one job
that does not check, since it is how to get to the right one.

Replies are (status, JSON). A bad argument raises BadRequest, which the bus makes a 400.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.app.bus import OK, BadRequest, Bus, Command, Effect, Refused, Reply, Spec
from zpkt.app.connections import LiveConnections
from zpkt.live import codegen, config, describe, openset, session
from zpkt.live import state as S
from zpkt.live.agent import only_reads
from zpkt.live.transport import McpResult

API_CALLERS = ("agent", "booth", "demo", "cli")  # who may use the jobs; the web page ("you") may not
MIN_BPM, MAX_BPM = 20.0, 999.0  # Live's own range
TRANSPORT_ACTIONS = ("play", "stop", "seek", "loop")

Job = Callable[[LiveConnections, Command], Reply]


# ---- reading arguments ---------------------------------------------------------------------------------------------


def text(args: Any, name: str, default: str | None = None) -> str:
    value = args.get(name)
    if value is None:
        if default is None:
            raise BadRequest(f"the body needs {name!r}")
        return default
    if not isinstance(value, str):
        raise BadRequest(f"{name!r} must be text")
    return value


def number(args: Any, name: str, default: float | None = None) -> float:
    value = args.get(name)
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise BadRequest(f"{name!r} must be a finite number" if name in args else f"the body needs {name!r}")
    return float(value)


def flag(args: Any, name: str, default: bool) -> bool:
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise BadRequest(f"{name!r} must be true or false")
    return value


def names(args: Any, name: str) -> list[str] | None:
    """An optional list of text; None when absent."""
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise BadRequest(f"{name!r} must be a list of text")
    return list(value)


def mcp_dict(res: McpResult) -> dict[str, Any]:
    """Live's reply as plain data (the API's `reply`)."""
    return dataclasses.asdict(res)


def expect_set(conn: LiveConnections, args: Any) -> None:
    """The wrong-set guard for a caller that names its set: Live must have that one open (a set it does not name
    passes, as in the bus)."""
    want = args.get("expect_set")
    if want is None:
        return
    have = openset.open_set_name(conn)
    if have and have != str(want).removesuffix(".als"):
        raise Refused(f"Live has {have} open; this call is for {want}. Open that set first.", 409)


# ---- the jobs ------------------------------------------------------------------------------------------------------


def live_run(conn: LiveConnections, cmd: Command) -> Reply:
    """Run a code string in Live (step A): the result as the Remote Script gave it."""
    expect_set(conn, cmd.args)
    res = conn.execute(text(cmd.args, "code"))
    return 200, {"ok": res.status == "ok", "reply": mcp_dict(res)}


def live_read(conn: LiveConnections, cmd: Command) -> Reply:
    """Run code that only reads. Code that changes anything is refused: use live.run for that."""
    code = text(cmd.args, "code")
    if not only_reads(code):
        raise BadRequest(
            "that code may change Live, or hides what it does; send it as live.run, which an agent needs your word for"
        )
    return live_run(conn, cmd)


def open_set(conn: LiveConnections, cmd: Command, forget: Callable[[], None]) -> Reply:
    name = text(cmd.args, "name").removesuffix(".als")
    try:
        seconds = session.open_set(conn, name, save_current=flag(cmd.args, "save_current", True))
    except session.Guard as exc:
        return 409, {"error": str(exc)}
    finally:
        forget()  # the wrong-set guard asks Live again
    return 200, {"ok": True, "name": name, "seconds": round(seconds, 2)}


def render_loop(conn: LiveConnections, cmd: Command) -> Reply:
    """Render through Live's Export dialog: the loop brace, or `start` and `length` in beats."""
    from zpkt.live import render, ui

    args = cmd.args
    start = number(args, "start") if args.get("start") is not None else None
    length = number(args, "length") if args.get("length") is not None else None
    if (start is None) != (length is None):
        raise BadRequest("give both 'start' and 'length', or neither")
    out = Path(text(args, "out"))
    path = out if out.is_absolute() or len(out.parts) > 1 else config.rig().renders_dir / out
    expect_set(conn, args)
    try:
        written = render.export(
            conn,
            path,
            start,
            length,
            mode=text(args, "mode", "Main"),
            bits=int(number(args, "bits", 32)),
            sample_rate=int(number(args, "sample_rate", 44100)),
        )
    except (session.Guard, ui.UiError, ValueError) as exc:
        return 409, {"error": f"export failed: {exc}"}
    return 200, {"ok": True, "files": [str(f) for f in written]}


def set_tempo(conn: LiveConnections, cmd: Command) -> Reply:
    bpm = number(cmd.args, "bpm")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise BadRequest(f"'bpm' is from {MIN_BPM:g} to {MAX_BPM:g}")
    expect_set(conn, cmd.args)
    return _ran(conn, codegen.gen_set_tempo(bpm).code)


def transport(conn: LiveConnections, cmd: Command) -> Reply:
    """Play, stop, seek to a beat, or set the arrangement loop."""
    args = cmd.args
    action = text(args, "action")
    if action == "play":
        code = "song.start_playing()"
    elif action == "stop":
        code = "song.stop_playing()"
    elif action == "seek":
        code = f"song.current_song_time = {number(args, 'beat')!r}"
    elif action == "loop":
        code = codegen.gen_set_arrangement_loop(
            flag(args, "on", True), number(args, "start", 0.0), number(args, "length")
        ).code
    else:
        raise BadRequest(f"'action' is one of {', '.join(TRANSPORT_ACTIONS)}")
    expect_set(conn, args)
    return _ran(conn, code)


def _ran(conn: LiveConnections, code: str) -> Reply:
    res = conn.execute(code)
    if res.status != "ok":
        return 502, {"error": res.error or "Live said no", "reply": mcp_dict(res)}
    return 200, {"ok": True, "result": res.result}


def state_take(conn: LiveConnections, cmd: Command) -> Reply:
    return 200, {"ok": True, "state": S.take(conn, names(cmd.args, "only"))}


def state_put(conn: LiveConnections, cmd: Command) -> Reply:
    state = cmd.args.get("state")
    if not isinstance(state, dict):
        raise BadRequest("the body needs 'state', a state object (hands live state take)")
    try:
        loaded = S.load_dict(dict(state))
    except (ValueError, KeyError, TypeError) as exc:
        raise BadRequest(f"'state' is not a state: {exc}") from None
    expect_set(conn, cmd.args)
    rows = S.put(conn, loaded, names(cmd.args, "only"))
    return 200, {"ok": True, "left": [list(r) for r in rows]}


def describe_keys(conn: LiveConnections, cmd: Command) -> Reply:
    keys = names(cmd.args, "keys")
    if not keys:
        raise BadRequest("the body needs 'keys', a list of state keys")
    found, missing = describe.look(conn, keys)
    return 200, {"ok": not missing, "found": found, "missing": missing}


def page_apply(conn: LiveConnections, cmd: Command) -> Reply:
    """Set a panel's values and render its next version (`hands panel apply`)."""
    import json

    from zpkt.live import mix, panel

    args = cmd.args
    out = Path(text(args, "out", "renders"))
    name = text(args, "name")
    values, changes = args.get("state"), args.get("spec")
    for what, value in (("state", values), ("spec", changes)):
        if value is not None and not isinstance(value, dict):
            raise BadRequest(f"{what!r} must be a JSON object")
    expect_set(conn, args)
    force = flag(args, "force", False)
    try:
        try:
            made = json.loads(panel._file(out, name).read_text())
        except (OSError, ValueError):
            made = None
        if isinstance(made, dict) and made.get("kind") == "mix":
            said = mix.apply(conn, made, out, state_values=values, spec=changes, force=force)
        else:
            said = panel.apply(conn, name, out, state_values=values, spec=changes, force=force)
    except panel.PanelError as exc:
        return 409, {"error": str(exc)}
    return 200, {"ok": True, "text": said}


# ---- the table -----------------------------------------------------------------------------------------------------

# kind -> (job, effect, guarded). Every job touches Live and is for the API's callers.
JOBS: dict[str, tuple[Job, Effect]] = {
    "live.run": (live_run, "move"),
    "live.read": (live_read, "read"),
    "live.render_loop": (render_loop, "move"),
    "live.set_tempo": (set_tempo, "move"),
    "live.transport": (transport, "move"),
    "state.take": (state_take, "read"),
    "state.put": (state_put, "move"),
    "page.apply": (page_apply, "move"),
    "describe": (describe_keys, "read"),
}


def register(bus: Bus, conn: LiveConnections) -> None:
    """Put the jobs on the bus. They name their own set (`expect_set`), so the bus's guard (for the desk's page) is
    off for them."""
    for kind, (job, effect) in JOBS.items():

        def run(cmd: Command, job: Job = job) -> Reply:
            return job(conn, cmd)

        bus.register(kind, Spec(run, effect, touches_live=True, guarded=False, callers=API_CALLERS))

    def opened(cmd: Command) -> Reply:
        return open_set(conn, cmd, lambda: bus.guard.forget() if bus.guard else None)

    bus.register("live.open_set", Spec(opened, "move", touches_live=True, guarded=False, callers=API_CALLERS))


__all__ = ["API_CALLERS", "JOBS", "OK", "register"]
