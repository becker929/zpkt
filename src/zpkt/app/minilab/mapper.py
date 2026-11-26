"""The MiniLab's map as a pure function: a control moved -> what to ask of the app.

`step(state, hit, view, tempo)` takes the small state the map keeps (Shift, focus, latch, pickup), the control that
moved (profile.Hit) and what the desk shows now (a View), and returns the new state and a list of actions: Submit (a
Command for the bus) or Show (two lines for the display). It does no I/O. The decisions (pickup, pages, the table of
what each control does in each layer) are contrib/mixdesk/pagercore.py's, the same file the pager runs in Live.

The shell (zpkt.app.adapters.midi) feeds it and sends the actions. A Submit with `coalesce` set is a stream (a knob, a
seek, the tempo): the shell keeps the latest per control for each tick and sends one batch (`merge`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from zpkt.app.minilab.core import pagercore
from zpkt.app.minilab.profile import Hit

ECHO_NEAR = 0.005  # a value we sent is "echoed" once Live reports it within this much (0..1)
SEEK_NEAR = 0.25  # a playhead we asked for is "reached" within this many beats


@dataclass(frozen=True)
class ControlView:
    """One control of the armed page as the desk shows it: its state key, place 0..1, shown text and name."""

    key: str
    n: float
    text: str = ""
    label: str = ""
    quantized: bool = False


@dataclass(frozen=True)
class PageView:
    name: str
    pad: int | None = None  # the bank-A pad (1-8) that arms it; None: the pager's default (its place)
    compare: Mapping[str, int] = field(default_factory=dict)  # pad slot (b1-b8) -> the compare state it switches to


@dataclass(frozen=True)
class View:
    """What the desk shows now, as plain data. `controls` has the armed page's working controls by slot (k1, f2, b3)."""

    page: int = 0
    pages: tuple[PageView, ...] = ()
    controls: Mapping[str, ControlView] = field(default_factory=dict)
    playing: bool = False
    pos: float = 0.0
    loop: str = "off"
    match: bool = True
    hearing: str = "now"  # now, pin or ref
    driving: bool = True  # the desk's pager is reporting: the tempo layer steps aside (auto)
    lit: str | None = None  # the pad slot of the armed page's compare state that is on now (derived), or None

    def cfg(self) -> dict[str, Any]:
        """The shape pagercore's page functions read."""
        return {
            "pages": [
                {
                    "name": p.name,
                    **({"pad": p.pad} if p.pad is not None else {}),
                    **({"compare": {"pads": dict(p.compare)}} if p.compare else {}),
                }
                for p in self.pages
            ]
        }


@dataclass(frozen=True)
class MapState:
    """What the map remembers between moves."""

    shift: bool = False
    page: int | None = None  # the page the pickup and the sent values belong to
    picked: frozenset[str] = frozenset()  # faders that have picked up on this page
    last_fader: Mapping[str, float] = field(default_factory=dict)
    last_knob: Mapping[str, int] = field(default_factory=dict)  # knob place (0..127) last seen, for fine steps
    sent: Mapping[str, float] = field(default_factory=dict)  # place we asked for, until Live reports it back
    focus: str | None = None
    focus_latched: bool = False
    zone: str | None = None  # what pitch bend holds now: pin, ref or None
    latched: bool = False  # Hold: keep the compare after the strip lets go
    hearing: str = "now"  # what we last asked to hear, or what the desk last said it hears
    desk_hearing: str = "now"  # what the desk last said it hears: only a change in it overrides `hearing`
    scrub_to: float | None = None


@dataclass(frozen=True)
class Submit:
    """A Command for the bus (the shell stamps who). `coalesce` names a stream: the latest of a kind replaces the last."""

    kind: str
    args: Mapping[str, Any] = field(default_factory=dict)
    coalesce: str | None = None


@dataclass(frozen=True)
class Show:
    """Two lines for the display."""

    line_1: str
    line_2: str = ""


Action = Submit | Show


# ---- keeping the state true to the desk ----------------------------------------------------------------------------


def sync(state: MapState, view: View) -> MapState:
    """The state after looking at the desk: a new page forgets pickup and sent values; what Live has reported back
    is no longer 'sent'; a focus that is gone is dropped."""
    if state.page != view.page:
        state = replace(state, page=view.page, picked=frozenset(), last_fader={}, last_knob={}, sent={}, scrub_to=None)
    sent = {s: n for s, n in state.sent.items() if s in view.controls and abs(view.controls[s].n - n) > ECHO_NEAR}
    scrub = state.scrub_to if state.scrub_to is not None and abs(view.pos - state.scrub_to) > SEEK_NEAR else None
    focus = state.focus if state.focus in view.controls else None
    hearing, desk_hearing = state.hearing, state.desk_hearing
    if view.hearing != desk_hearing:  # someone else (the web) changed it; Live's echo of our own ask is not news
        hearing, desk_hearing = view.hearing, view.hearing
    return replace(state, sent=sent, scrub_to=scrub, focus=focus, hearing=hearing, desk_hearing=desk_hearing)


def _place(state: MapState, view: View, slot: str) -> float:
    """Where a control is: what we last asked for until Live reports it, else what the desk shows."""
    return state.sent.get(slot, view.controls[slot].n)


# ---- the actions' shapes ---------------------------------------------------------------------------------------------


def _set(page: int, slot: str, n: float) -> Submit:
    clamped = round(max(0.0, min(1.0, n)), 6)
    return Submit("page.set", {"page": page, "controls": [{"slot": slot, "n": clamped}]}, "set")


def _arm(page: int) -> Submit:
    return Submit("page.arm", {"page": page})


def _show_control(view: View, slot: str) -> Show:
    c = view.controls[slot]
    return Show(c.label or slot, c.text)


def _show_page(view: View, page: int) -> Show:
    name = view.pages[page].name if 0 <= page < len(view.pages) else f"Page {page + 1}"
    return Show(name, f"page {page + 1} of {len(view.pages)}")


def _pressed(hit: Hit) -> bool:
    return hit.value > 0


# ---- the roles -------------------------------------------------------------------------------------------------------
# Each takes (state, hit, view, arg) and returns (state, actions). `arg` is the table row's argument.

Result = tuple[MapState, list[Action]]
Role = Callable[[MapState, Hit, View, Any], Result]


def _knob(state: MapState, hit: Hit, view: View, slot: str) -> Result:
    if slot not in view.controls:
        return state, []
    n = hit.value / 127.0
    state = replace(state, sent={**state.sent, slot: n}, last_knob={**state.last_knob, slot: hit.value})
    return state, [_set(view.page, slot, n)]


def _knob_fine(state: MapState, hit: Hit, view: View, slot: str) -> Result:
    last = state.last_knob.get(slot)
    knobs = {**state.last_knob, slot: hit.value}
    if slot not in view.controls or last is None:  # the first report of a knob moves nothing
        return replace(state, last_knob=knobs), []
    n = pagercore().fine_value(_place(state, view, slot), last, hit.value)
    return replace(state, last_knob=knobs, sent={**state.sent, slot: n}), [_set(view.page, slot, n)]


def _fader(state: MapState, hit: Hit, view: View, slot: str) -> Result:
    n = hit.value / 127.0
    last = state.last_fader.get(slot)
    state = replace(state, last_fader={**state.last_fader, slot: n})
    if slot not in view.controls:
        return state, []
    if slot not in state.picked and pagercore().picks_up(n, last, view.controls[slot].n):
        state = replace(state, picked=state.picked | {slot})
    if slot not in state.picked:
        return state, []
    return replace(state, sent={**state.sent, slot: n}), [_set(view.page, slot, n)]


def _toggle_pad(state: MapState, hit: Hit, view: View, slot: str) -> Result:
    if not _pressed(hit) or slot not in view.controls:
        return state, []
    return state, [Submit("mix.toggle", {"slot": slot, "page": view.page})]


def _page_pad(state: MapState, hit: Hit, view: View, pad: int) -> Result:
    """A pad arms a page; on a page with compare states, a pad that holds one switches the mix to it instead."""
    if _pressed(hit) and pagercore().compare_state(view.cfg(), view.page, pad) is not None:
        return state, [Submit("page.compare", {"page": view.page, "slot": f"b{pad}"})]
    page = pagercore().page_for_pad(view.cfg(), pad, view.page) if _pressed(hit) else None
    return (state, []) if page is None else (state, [_arm(page), _show_page(view, page)])


def _page_step(state: MapState, hit: Hit, view: View, step: int) -> Result:
    page = pagercore().step_page(view.page, step, len(view.pages)) if _pressed(hit) and view.pages else None
    return (state, []) if page is None else (state, [_arm(page), _show_page(view, page)])


def _window_step(state: MapState, hit: Hit, view: View, step: int) -> Result:
    if not _pressed(hit):
        return state, []
    mode = pagercore().loop_window(view.loop, step)
    return state, [Submit("transport", {"action": "loop", "loop": mode}), Show("Loop", mode)]


def _focus_step(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    steps = pagercore().relative_step(hit.value)
    if state.focus_latched or not steps or not view.controls:
        return state, []
    core = pagercore()
    order = core.focus_order(list(view.controls))
    focus = state.focus
    for _ in range(abs(steps)):
        focus = core.step_focus(order, focus, 1 if steps > 0 else -1)
    return replace(state, focus=focus), [] if focus is None else [_show_control(view, focus)]


def _focus_reset(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    if not _pressed(hit) or state.focus is None or state.focus not in view.controls:
        return state, []
    control = view.controls[state.focus]
    forgotten = {k: v for k, v in state.sent.items() if k != state.focus}
    return replace(state, sent=forgotten), [
        Submit("mix.reset", {"keys": [control.key]}),
        Show("Reset", control.label or state.focus),
    ]


def _focus_set(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    """The mod strip: the focused control follows it."""
    if state.focus is None or state.focus not in view.controls:
        return state, []
    n = hit.value / 127.0
    return replace(state, sent={**state.sent, state.focus: n}), [_set(view.page, state.focus, n)]


def _focus_select(state: MapState, hit: Hit, view: View, count: int) -> Result:
    """A key: a place in 25 steps for the focused control."""
    if not _pressed(hit) or state.focus is None or state.focus not in view.controls:
        return state, []
    n = pagercore().key_position(hit.number, count=count)
    return replace(state, sent={**state.sent, state.focus: n}), [_set(view.page, state.focus, n)]


def _group_next(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    if not _pressed(hit) or state.focus_latched:
        return state, []
    core = pagercore()
    focus = core.next_group_focus(core.focus_order(list(view.controls)), state.focus)
    return replace(state, focus=focus), [] if focus is None else [_show_control(view, focus)]


def _scrub(state: MapState, hit: Hit, view: View, beats: float) -> Result:
    steps = pagercore().relative_step(hit.value)
    if not steps:
        return state, []
    target = max(0.0, (state.scrub_to if state.scrub_to is not None else view.pos) + steps * beats)
    return replace(state, scrub_to=target), [Submit("transport", {"action": "seek", "beat": target}, "seek")]


def _hear(state: MapState, what: str) -> Result:
    if state.hearing == what:
        return state, []
    return replace(state, hearing=what), [Submit("monitor.hear", {"hearing": what}), Show("Hear", what)]


def _hear_hold(state: MapState, hit: Hit, view: View, pair: tuple[str, str]) -> Result:
    """Pitch bend: hold Pin (up) or Ref (down); let go and Now comes back, unless Hold has latched the compare."""
    core = pagercore()
    zone = core.bend_hold(core.bend_amount(hit.value), state.zone, pair[0], pair[1])
    if zone == state.zone:
        return state, []
    state = replace(state, zone=zone)
    if zone is not None:
        return _hear(state, zone)
    return (state, []) if state.latched else _hear(state, "now")


def _latch_compare(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    if not _pressed(hit):
        return state, []
    state = replace(state, latched=not state.latched)
    shown: list[Action] = [Show("Hold", "latched" if state.latched else "off")]
    if not state.latched and state.zone is None:
        state, back = _hear(state, "now")
        return state, [*back, *shown]
    return state, shown


def _latch_focus(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    if not _pressed(hit):
        return state, []
    state = replace(state, focus_latched=not state.focus_latched)
    return state, [Show("Focus", "latched" if state.focus_latched else "free")]


def _tempo_fader(state: MapState, hit: Hit, view: View, _arg: Any) -> Result:
    bpm = pagercore().tempo_from_fader(hit.value)
    return state, [Submit("tempo.set", {"bpm": bpm}, "tempo"), Show("Tempo", f"{bpm} BPM")]


def _tempo_scale(state: MapState, hit: Hit, view: View, factor: float) -> Result:
    return (state, [Submit("tempo.scale", {"factor": factor})]) if _pressed(hit) else (state, [])


def _action(state: MapState, hit: Hit, view: View, name: str) -> Result:
    """A named action (pagercore.ACTIONS) on a press."""
    if not _pressed(hit):
        return state, []
    if pagercore().ACTIONS.get(name) == "later":
        return state, [Show("Not built", name)]
    return _ACTIONS[name](state, view)


def _toggle_play(state: MapState, view: View) -> Result:
    return state, [Submit("transport", {"action": "pause" if view.playing else "play"})]


def _cycle_loop(state: MapState, view: View) -> Result:
    mode = pagercore().loop_window(view.loop, 1)
    return state, [Submit("transport", {"action": "loop", "loop": mode}), Show("Loop", mode)]


def _match(state: MapState, view: View) -> Result:
    return state, [Submit("monitor.choose", {"match": not view.match}), Show("Match", "off" if view.match else "on")]


_ACTIONS: dict[str, Callable[[MapState, View], Result]] = {
    "transport.toggle": _toggle_play,
    "transport.stop": lambda s, v: (s, [Submit("transport", {"action": "pause"})]),
    "loop.cycle": _cycle_loop,
    "hear.now": lambda s, v: _hear(s, "now"),
    "hear.pin": lambda s, v: _hear(s, "pin"),
    "hear.ref": lambda s, v: _hear(s, "ref"),
    "history.undo": lambda s, v: (s, [Submit("history.undo"), Show("Undo")]),
    "history.redo": lambda s, v: (s, [Submit("history.redo"), Show("Redo")]),
    "history.checkpoint": lambda s, v: (s, [Submit("history.checkpoint"), Show("Version", "made")]),
    "monitor.match": _match,
    "pin.set": lambda s, v: (s, [Submit("monitor.pin"), Show("Pin", "set")]),
}

ROLES: dict[str, Role] = {
    "knob": _knob,
    "knob_fine": _knob_fine,
    "fader": _fader,
    "toggle_pad": _toggle_pad,
    "page_pad": _page_pad,
    "page_step": _page_step,
    "window_step": _window_step,
    "focus_step": _focus_step,
    "focus_reset": _focus_reset,
    "focus_set": _focus_set,
    "focus_select": _focus_select,
    "group_next": _group_next,
    "scrub": _scrub,
    "hear_hold": _hear_hold,
    "latch_compare": _latch_compare,
    "latch_focus": _latch_focus,
    "tempo_fader": _tempo_fader,
    "tempo_scale": _tempo_scale,
    "action": _action,
}


# ---- one move --------------------------------------------------------------------------------------------------------


def step(state: MapState, hit: Hit, view: View, tempo: bool = False) -> Result:
    """What one control's move does. Shift is the map's own: it only changes what the next move means."""
    state = sync(state, view)
    if hit.name == "shift":
        return replace(state, shift=_pressed(hit)), []
    row = pagercore().row_for(hit.name, state.shift or hit.shifted, tempo)
    if row is None:
        return state, []
    return ROLES[row[2]](state, hit, view, row[3])


# ---- streams ---------------------------------------------------------------------------------------------------------


def merge(pending: list[Submit], action: Submit) -> list[Submit]:
    """`pending` with `action` added: a stream (same `coalesce`) keeps only its latest, and page.set sets of one page
    become one batch with the latest place of each control. Order of first appearance is kept."""
    if action.coalesce is None:
        raise ValueError("only a stream (a Submit with coalesce set) is merged")
    for i, old in enumerate(pending):
        if old.coalesce != action.coalesce:
            continue
        if action.kind == "page.set":
            if old.args["page"] != action.args["page"]:
                continue
            latest = {c["slot"]: c["n"] for c in (*old.args["controls"], *action.args["controls"])}
            joined = Submit(
                "page.set",
                {"page": action.args["page"], "controls": [{"slot": s, "n": n} for s, n in latest.items()]},
                "set",
            )
            return [*pending[:i], joined, *pending[i + 1 :]]
        return [*pending[:i], action, *pending[i + 1 :]]
    return [*pending, action]
