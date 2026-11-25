"""The desk's commands: one handler for each kind of thing asked of the app, registered on the bus.

Each handler takes the desk and the Command and answers (status, JSON). The web adapter's old routes (POST /api/page,
/api/undo, ...) are these same commands under their old paths (`POST_PATHS`), so the page, the MiniLab, an agent and
the API all pass one door. A bad body raises BadRequest; the bus turns it into a 400.
"""

from __future__ import annotations

import dataclasses
import math
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from zpkt.app import deskstate as D
from zpkt.app import effects, monitor, pages, surfaces
from zpkt.app import options as O
from zpkt.app.bus import OK, BadRequest, Bus, Command, Reply
from zpkt.live import describe, tempo
from zpkt.live import state as S
from zpkt.live.describe import Description

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

Handler = Callable[["Desk", Command], Reply]

# the old routes: path -> command kind (the web adapter serves each under its path)
POST_PATHS: dict[str, str] = {
    "/api/page": "page.arm",
    "/api/toggle": "mix.toggle",
    "/api/transport": "transport",
    "/api/monitor": "monitor.choose",
    "/api/restart": "pager.restart",
    "/api/surface/make": "surface.make",
    "/api/surface/save": "surface.save",
    "/api/surface/remove": "surface.remove",
    "/api/undo": "history.undo",
    "/api/redo": "history.redo",
    "/api/checkpoint": "history.checkpoint",
    "/api/revert": "history.revert",
}


# ---- reading a body ------------------------------------------------------------------------------------------------


def _int(body: Any, name: str) -> int:
    try:
        return int(body[name])
    except KeyError:
        raise BadRequest(f"the body needs {name!r}") from None
    except (TypeError, ValueError):
        raise BadRequest(f"{name!r} must be a whole number") from None


def _float(body: Any, name: str) -> float:
    try:
        value = float(body[name])
    except KeyError:
        raise BadRequest(f"the body needs {name!r}") from None
    except (TypeError, ValueError):
        raise BadRequest(f"{name!r} must be a number") from None
    if not math.isfinite(value):
        raise BadRequest(f"{name!r} must be a finite number")
    return value


def _str(body: Any, name: str, default: str | None = None) -> str:
    if name not in body or body[name] is None:
        if default is None:
            raise BadRequest(f"the body needs {name!r}")
        return default
    return str(body[name])


def raw_from_norm(d: Description, n: float) -> float:
    """The raw value for a position 0..1 on a control, as the pager's set_norm gives it: linear between the
    parameter's min and max; a switch or list lands on a step."""
    n = max(0.0, min(1.0, n))
    if d["kind"] == "switch":
        return d["max"] if n >= 0.5 else d["min"]
    value = d["min"] + n * (d["max"] - d["min"])
    steps = d["steps"]
    if d["kind"] == "choice" and steps and steps > 1:
        value = d["min"] + round(n * (steps - 1)) * (d["max"] - d["min"]) / (steps - 1)
    return value


def _norms(desk: Desk, body: Any) -> list[list[Any]]:
    """`norms`: [[state key, position 0..1], ...] as writes (the shell drags positions, Live takes raw values)."""
    norms = body["norms"]
    if not (isinstance(norms, list) and norms and all(isinstance(x, list) and len(x) == 2 for x in norms)):
        raise BadRequest("'norms' is a list of [state key, position from 0 to 1]")
    keys = [str(x[0]) for x in norms]
    try:
        found = describe.describe(desk.conn, keys)
    except describe.Missing as exc:
        raise BadRequest(f"the set does not have: {'; '.join(exc.missing)}") from None
    return [[str(k), raw_from_norm(found[str(k)], _float({"n": n}, "n"))] for k, n in norms]


def _pairs(desk: Desk, body: Any) -> list[list[Any]]:
    """`writes`: [[state key, raw], ...] or [[state key, raw, shown], ...]; or `norms` (see _norms)."""
    if "norms" in body:
        return _norms(desk, body)
    writes = body.get("writes")
    if not isinstance(writes, list) or not writes:
        raise BadRequest("the body needs 'writes', a list of [state key, raw value]")
    out: list[list[Any]] = []
    for w in writes:
        if not (isinstance(w, list) and len(w) in (2, 3) and isinstance(w[0], str)):
            raise BadRequest("each write is [state key, raw value] or [state key, raw value, shown text]")
        if isinstance(w[1], bool) or not isinstance(w[1], int | float) or not math.isfinite(float(w[1])):
            raise BadRequest(f"the raw value of {w[0]!r} must be a finite number")
        out.append(list(w))
    return out


# ---- the MiniLab's pages and switches ------------------------------------------------------------------------------


def page_arm(desk: Desk, cmd: Command) -> Reply:
    desk.call(f"m.DESK.arm({_int(cmd.args, 'page')})")
    return OK


def mix_toggle(desk: Desk, cmd: Command) -> Reply:
    slot = _str(cmd.args, "slot")
    if not (slot[:1] == "b" and slot[1:].isdigit()):
        return 400, {"error": "bad slot"}
    desk.call(f"m.DESK.toggle({slot!r}, {_int(cmd.args, 'page')})")
    return OK


def mix_set(desk: Desk, cmd: Command) -> Reply:
    """Move controls: [[state key, raw], ...] from you or an agent. One history entry (an agent's group is one)."""
    return _move(desk, cmd, _pairs(desk, cmd.args))


def _move(desk: Desk, cmd: Command, pairs: list[list[Any]]) -> Reply:
    desk.monitor.leave_pin()  # moving a control while the Pin is heard starts from Now
    entry = desk.history.record(pairs, cmd.who, cmd.group)
    try:
        missing = desk.write(pairs)
    except Exception:
        desk.history.forget(entry)
        raise
    desk.history.flush_changes()
    desk.push(desk.history.view())
    desk.push_app(desk.monitor.message())
    return 200, {"ok": True, "entry": entry and entry["id"], "missing": missing}


def _described(desk: Desk, keys: list[str]) -> dict[str, Description]:
    """Descriptions of `keys`, asking Live only for those not seen yet: a knob's stream asks a few times a second, and
    a parameter's range does not change while the set is open."""
    with desk.lock:
        known = {k: desk.descriptions[k] for k in keys if k in desk.descriptions}
    missing = [k for k in keys if k not in known]
    if missing:
        found = describe.describe(desk.conn, missing)
        with desk.lock:
            desk.descriptions.update(found)
        known.update(found)
    return known


def _page_keys(desk: Desk, page: int, slots: list[str]) -> dict[str, str]:
    """{slot: state key} of the controls on `page` that work (the pager reports a key for each)."""
    values = desk.snapshot()["values"]
    return {s: str(v["key"]) for s in slots if (v := values.get(f"{page}:{s}")) and v.get("key") and not v.get("err")}


def page_set(desk: Desk, cmd: Command) -> Reply:
    """Put the page's controls at places 0..1: {"page": 0, "controls": [{"slot": "k1", "n": 0.4}, ...]}. What the
    MiniLab sends, one batch for a tick of knobs."""
    page = _int(cmd.args, "page")
    controls = cmd.args.get("controls")
    if not (isinstance(controls, list) and controls and all(isinstance(c, dict) and "slot" in c for c in controls)):
        raise BadRequest("'controls' is a list of {slot, n}")
    keys = _page_keys(desk, page, [str(c["slot"]) for c in controls])
    wanted = [c for c in controls if str(c["slot"]) in keys]
    if not wanted:
        return 200, {"ok": True, "entry": None, "missing": [str(c["slot"]) for c in controls]}
    found = _described(desk, [keys[str(c["slot"])] for c in wanted])
    pairs = [[keys[str(c["slot"])], raw_from_norm(found[keys[str(c["slot"])]], _float(c, "n"))] for c in wanted]
    return _move(desk, cmd, pairs)


def mix_reset(desk: Desk, cmd: Command) -> Reply:
    """Put controls back to their default: {"keys": [state key, ...]}. One history entry, so undo takes it back."""
    keys = cmd.args.get("keys")
    if not (isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys)):
        raise BadRequest("'keys' is a list of state keys")
    try:
        found = _described(desk, keys)
    except describe.Missing as exc:
        raise BadRequest(f"the set does not have: {'; '.join(exc.missing)}") from None
    pairs = [[k, found[k]["default"]] for k in keys if found[k]["default"] is not None]
    if not pairs:
        return 200, {"ok": True, "entry": None, "missing": []}
    return _move(desk, cmd, pairs)


def tempo_set(desk: Desk, cmd: Command) -> Reply:
    tempo.set_tempo(desk.conn, _float(cmd.args, "bpm"))
    return OK


def tempo_scale(desk: Desk, cmd: Command) -> Reply:
    factor = _float(cmd.args, "factor")
    if factor <= 0:
        raise BadRequest("'factor' must be above 0")
    tempo.scale_tempo(desk.conn, factor)
    return OK


def transport(desk: Desk, cmd: Command) -> Reply:
    action = _str(cmd.args, "action")
    if action == "seek":
        desk.monitor.transport("seek", beat=_float(cmd.args, "beat"))
    elif action == "loop":
        kind = _str(cmd.args, "loop")
        if kind not in D.LOOPS:
            return 400, {"error": "bad loop"}
        desk.monitor.transport("loop", loop=kind)
    elif action in ("play", "pause"):
        desk.monitor.transport(action)
    else:
        return 400, {"error": "bad action"}
    return OK


def monitor_choose(desk: Desk, cmd: Command) -> Reply:
    now = desk.monitor_choice()
    slot, ref = _str(cmd.args, "slot", now["slot"]), _str(cmd.args, "ref", now["ref"])
    if slot not in D.SLOTS or ref not in desk.analysis()["sources"]:
        return 400, {"error": "bad slot or ref"}
    if "match" in cmd.args:
        desk.set_match(bool(cmd.args["match"]))
    desk.monitor.select(slot, ref)
    desk.push_full()
    return OK


def monitor_hear(desk: Desk, cmd: Command) -> Reply:
    """Hear Now, the Pin or the Reference."""
    what = _str(cmd.args, "hearing")
    if what not in monitor.HEARINGS:
        return 400, {"error": f"hearing is one of {', '.join(monitor.HEARINGS)}"}
    if what == "ref" and desk.monitor_choice()["ref"] not in desk.analysis()["sources"]:
        return 400, {"error": "there is no reference to hear: run analyze.py first"}
    desk.monitor.hear(what)
    return 200, {"ok": True, "hear": desk.monitor.message()}


def monitor_pin(desk: Desk, cmd: Command) -> Reply:
    """Set the mix as it is now aside as the Pin."""
    desk.monitor.make_pin(cmd.who)
    desk.push(desk.history.view())
    return 200, {"ok": True, "hear": desk.monitor.message()}


def pager_restart(desk: Desk, cmd: Command) -> Reply:
    desk.restart_pager()
    return OK


# ---- surfaces ------------------------------------------------------------------------------------------------------


def surface_make(desk: Desk, cmd: Command) -> Reply:
    text = _str(cmd.args, "text", "").strip()
    if not text:
        return 400, {"error": "say what the surface is for"}
    threading.Thread(target=desk.make_surface, args=(text[:2000],), daemon=True).start()
    return OK


def surface_save(desk: Desk, cmd: Command) -> Reply:
    """A ready-made surface: the same checks as a made one, no model."""
    if not isinstance(cmd.args.get("surface"), dict):
        raise BadRequest("the body needs 'surface', a surface object")
    try:
        surface = surfaces.validate(cmd.args["surface"], desk.inventory(), desk.page_names())
        path = surfaces.save(surface, desk.settings.set_name, _str(cmd.args, "prompt", ""), desk.settings.surfaces_dir)
    except surfaces.SurfaceError as exc:
        return 400, {"error": str(exc)}
    idx = desk.adopt_surface(path, surface)
    return 200, {"ok": True, "file": path.name, "page": idx, "notes": surface["notes"]}


def surface_remove(desk: Desk, cmd: Command) -> Reply:
    # stay on the page that was armed (by name: the indexes after the removed one shift)
    was, old = desk.page_names(), desk.snapshot()["page"]
    armed = was[old] if 0 <= old < len(was) else None
    try:
        surfaces.remove(desk.settings.set_name, _str(cmd.args, "file", ""), desk.settings.surfaces_dir)
    except surfaces.SurfaceError as exc:
        return 400, {"error": str(exc)}
    desk.restart_pager()
    names = desk.page_names()
    idx = names.index(armed) if armed in names else max(0, min(old, len(names)) - 1)
    desk.call(f"m.DESK.arm({idx})")
    desk.push({"t": "desk", "open": idx})
    return OK


# ---- history -------------------------------------------------------------------------------------------------------


def _step(desk: Desk, cmd: Command, undo: bool) -> Reply:
    desk.monitor.leave_pin()
    pairs, e = desk.history.undo(cmd.who) if undo else desk.history.redo(cmd.who)
    missing = desk.write(pairs)
    desk.push(desk.history.view())
    desk.push_app(desk.monitor.message())
    return 200, {"ok": True, "entry": e and e["id"], "missing": missing}


def history_undo(desk: Desk, cmd: Command) -> Reply:
    return _step(desk, cmd, undo=True)


def history_redo(desk: Desk, cmd: Command) -> Reply:
    return _step(desk, cmd, undo=False)


def history_checkpoint(desk: Desk, cmd: Command) -> Reply:
    name = str(cmd.args.get("name") or time.strftime("cp-%H%M%S")).strip()
    try:
        e = desk.make_checkpoint(name, cmd.who)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    desk.push(desk.history.view())
    return 200, {"ok": True, "name": e["name"]}


def history_revert(desk: Desk, cmd: Command) -> Reply:
    to = _str(cmd.args, "to")
    keys = cmd.args.get("keys")
    if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
        raise BadRequest("'keys' must be a list of state keys")
    try:
        desk.history.load(to)  # the name is checked before anything changes
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    except FileNotFoundError:
        raise BadRequest(f"there is no checkpoint named {to!r}") from None
    desk.monitor.leave_pin()
    if cmd.args.get("all"):
        # the whole mix: the desk's controls as one undoable step, then everything else (not undoable, so a
        # checkpoint of the mix as it was comes first), heard on W so the monitor tracks stay put
        desk.make_checkpoint(time.strftime("before-revert-%H%M%S"), who="sys")
        now = desk.monitor_choice()
        if now["slot"] != "W":
            desk.monitor.choose("W", now["ref"])
        pairs, _ = desk.history.revert(to, who=cmd.who)  # type: ignore[arg-type]
        desk.write(pairs)
        rows = S.put(desk.conn, S.load(desk.history.folder() / f"{to}.json"))
        desk.push(desk.history.view())
        return 200, {"ok": True, "left": [list(r) for r in rows if not r[0].startswith("mon ")][:20]}
    pairs, _ = desk.history.revert(to, keys, cmd.who)  # type: ignore[arg-type]
    missing = desk.write(pairs)
    desk.push(desk.history.view())
    return 200, {"ok": True, "moved": len(pairs), "missing": missing}


# ---- Options -------------------------------------------------------------------------------------------------------


def _option_args(cmd: Command) -> tuple[str, str]:
    return _str(cmd.args, "option"), _str(cmd.args, "version")


def options_list(desk: Desk, cmd: Command) -> Reply:
    """Every Option, with its Versions and numbers, and the Version on the Hear bar."""
    return 200, {"ok": True, **desk.options.message()}


def options_get(desk: Desk, cmd: Command) -> Reply:
    try:
        return 200, {"ok": True, "option": desk.options.get(_str(cmd.args, "option"))}
    except O.BadOption as exc:
        raise BadRequest(str(exc)) from None


def options_make(desk: Desk, cmd: Command) -> Reply:
    """Ask for an Option: {title, versions: [{label, writes}], range?}. It is queued and rendered one Version at a time."""
    try:
        return 200, {"ok": True, "option": desk.options.make(dict(cmd.args))}
    except O.BadOption as exc:
        raise BadRequest(str(exc)) from None


def options_show(desk: Desk, cmd: Command) -> Reply:
    """Put a Version on the Hear bar: its loudness, peak, spectrum and gap to the base."""
    option, version = _option_args(cmd)
    try:
        return 200, {"ok": True, **desk.options.show(option, version)}
    except (O.BadOption, ValueError) as exc:
        raise BadRequest(str(exc)) from None


def options_pick(desk: Desk, cmd: Command) -> Reply:
    """Make a Version Now: its values go onto the mix as one move (one undo), as if you had set them."""
    option_id, version_id = _option_args(cmd)
    try:
        version = O.find_version(desk.options.get(option_id), version_id)
    except O.BadOption as exc:
        raise BadRequest(str(exc)) from None
    if version["status"] != "ready":
        raise BadRequest(f"Version {version_id} is {version['status']}; pick one that is ready")
    if not version["writes"]:
        raise BadRequest(
            f"Version {version['label']!r} is not a set of values on the mix, so there is nothing to put on Now. "
            "Hear it, or make its settings by hand."
        )
    reply = mix_set(desk, dataclasses.replace(cmd, kind="mix.set", args={"writes": version["writes"]}))
    if reply[0] == 200:
        desk.options.keep_now(option_id, version_id)
        desk.push_app(desk.options.message())
    return reply


# ---- the table -----------------------------------------------------------------------------------------------------

# kind -> (handler, touches Live). Whether a command is a read, a make or a move is in zpkt.app.effects.
COMMANDS: dict[str, tuple[Handler, bool]] = {
    "page.arm": (page_arm, True),
    "mix.toggle": (mix_toggle, True),
    "mix.set": (mix_set, True),
    "page.set": (page_set, True),
    "mix.reset": (mix_reset, True),
    "tempo.set": (tempo_set, True),
    "tempo.scale": (tempo_scale, True),
    "transport": (transport, True),
    "monitor.choose": (monitor_choose, True),
    "monitor.hear": (monitor_hear, True),
    "monitor.pin": (monitor_pin, True),
    "pager.restart": (pager_restart, True),
    "page.lint": (pages.lint, True),
    "page.make": (pages.make, True),
    "page.layout": (pages.layout_of, True),
    "surface.make": (surface_make, False),
    "surface.save": (surface_save, True),
    "surface.remove": (surface_remove, True),
    "history.undo": (history_undo, True),
    "history.redo": (history_redo, True),
    "history.checkpoint": (history_checkpoint, True),
    "history.revert": (history_revert, True),
    "options.list": (options_list, False),
    "options.get": (options_get, False),
    "options.make": (options_make, False),
    "options.show": (options_show, False),
    "options.pick": (options_pick, True),
}


def register_all(bus: Bus, desk: Desk) -> None:
    """Put every desk command on the bus."""
    for kind, (handler, touches) in COMMANDS.items():

        def run(cmd: Command, handler: Handler = handler) -> Reply:
            return handler(desk, cmd)

        effects.register(bus, kind, run, touches_live=touches)
