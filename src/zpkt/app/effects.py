"""What each command does: the one table that says whether a command is a read, a make or a move.

The class decides the bus's checks (zpkt.app.bus):

- read: it looks. Nothing changes in Live or on disk.
- make: it makes or changes pages, files or checkpoints. Live's set stays as it is. An agent may.
- move: it changes Live (the mix, the tempo, the transport, what is heard, the pager and what the MiniLab's controls
  do) or runs code or a build there. An agent needs your word, and the wrong-set guard holds it.

Every module that puts commands on the bus takes the class from here (`register`), so a command without a line in
this table cannot start. tests/app/test_effects.py writes the whole list out again: a change here is a decision.

These lines are decisions worth their reason:

- `pager.restart` and `page.arm` are moves. They reload code into Live and change which page the MiniLab's controls
  work, under your hands.
- `page.open` is a move for the same reason: it puts a saved page on the desk and the MiniLab and arms it. An agent
  drafts a page and gives you its link; opening it is yours.
- `page.make` is a make though it puts the new page on the desk. Making pages is what an agent is for, and the
  handler checks the open set itself before anything is saved.
- `page.draft` is a make, also when it writes over a page the agent made before that is on the desk: the page is
  redrawn where it is and the desk stays on the page it was on. No value of the mix moves.
- `meter.install` is a move: it loads a device on Main. It is one history entry, and undo takes the device off.
- `page.compare` is a move: it writes a compare state's values into the mix. It is the press of a pad, on the screen
  or on the MiniLab. An agent makes the states; it never switches them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zpkt.app.bus import Bus, Command, Effect, Reply, Spec

EFFECTS: dict[str, Effect] = {
    # the desk (zpkt.app.commands)
    "page.arm": "move",
    "mix.toggle": "move",
    "mix.set": "move",
    "page.set": "move",
    "mix.reset": "move",
    "mix.describe": "read",
    "tempo.set": "move",
    "tempo.scale": "move",
    "transport": "move",
    "monitor.choose": "move",
    "monitor.hear": "move",
    "monitor.pin": "make",
    "pager.restart": "move",
    "page.lint": "read",
    "page.make": "make",
    "page.layout": "read",
    "page.list": "read",
    "page.organize": "move",
    "page.open": "move",
    "page.compare": "move",
    "surface.make": "make",
    "surface.save": "make",
    "surface.remove": "move",
    "history.undo": "move",
    "history.redo": "move",
    "history.checkpoint": "make",
    "history.revert": "move",
    "history.back": "move",
    "meter.install": "move",
    "arrangement.read": "read",
    # the jobs (zpkt.app.jobs)
    "live.run": "move",
    "live.read": "read",
    "live.open_set": "move",
    "live.render_loop": "move",
    "live.set_tempo": "move",
    "live.transport": "move",
    "state.take": "read",
    "state.put": "move",
    "panel.apply": "move",
    "page.apply": "move",  # the older name of panel.apply
    "describe": "read",
    # the agents' commands (zpkt.app.agent_commands)
    "page.draft": "make",
    "desk.state": "read",
    "state.read": "read",  # the older name of desk.state
    "measurement.read": "read",
}


def effect_of(kind: str) -> Effect:
    """The class of a command kind. A kind with no line is an error that says where to add it."""
    try:
        return EFFECTS[kind]
    except KeyError:
        raise ValueError(
            f"the command {kind!r} has no class: add it to EFFECTS in zpkt.app.effects as a read, a make or a move"
        ) from None


def register(bus: Bus, kind: str, handler: Callable[[Command], Reply], **spec: Any) -> None:
    """Put `handler` on the bus as `kind`, with the class the table gives. `spec` is the rest of the Spec."""
    bus.register(kind, Spec(handler, effect_of(kind), **spec))
