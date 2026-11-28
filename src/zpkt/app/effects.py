"""What each command does: the one table that says whether a command is a read, a make or a move.

The class decides the bus's checks (zpkt.app.bus):

- read: it looks. Nothing changes in Live or on disk.
- make: it makes or changes pages, files or checkpoints. Live's set stays as it is. An agent may.
- move: it changes Live (the mix, the tempo, the transport, what is heard, the pager and what the MiniLab's controls
  do) or runs code or a build there. An agent needs your word, and the wrong-set guard holds it. The moves an
  agent may ask for on its own are in AGENT_MAY, below: `live.change`, `ability.run`, whose word you gave before,
  and `render.bounce`, which changes nothing of the mix.

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
- `live.change` is a move, and the one move an agent may ask for with no word of yours (AGENT_MAY). Anthony,
  26 November 2026: the agent may set values and add, bypass, enable and reorder devices on existing tracks itself:
  act, then undo. The command can do nothing else: no device is removed, no track made, no routing or clip
  changed, no code run. It checks the whole batch before anything moves (the set's own names and ranges, never a
  monitor track, never Main's desk devices), saves a version first, and is one History row that one undo takes
  back. Every other move (`mix.set`, `transport`, `live.run`, ...) still needs your word from an agent.
- `live.propose` is a move that an agent may NOT ask for on its own, and the way it gets your word. Anthony,
  26 November 2026: structure and code are "ask first". The batch may also remove a device, make a track and run
  code. `live.propose.check` (a read) checks it whole and writes its card; the Ask tool gate shows the card in the
  chat and waits for your tap; only after "Do it" does the gate send `live.propose` with your word
  (zpkt.app.propose, zpkt.app.ask.tools). Like `live.run` it is for the API's callers, never the web page. Undo
  takes back its values and its added or moved devices, and leaves a removed device, a new track and code.
- `ability.run` is a move, and the second move an agent may ask for with no word of yours at the time (AGENT_MAY).
  Anthony, 26 November 2026: "an 'Always' button which adds the code to an auto allowed set, as new abilities with
  documentation and everything, run the same as other tools." The word was given before: an ability is a code
  step of a proposal that you answered with "Always", kept as the exact code the card showed (zpkt.app.abilities).
  What an agent chooses at a run is the arguments, which are checked against the declared parameters and passed
  as data. The command can run nothing that was not kept that way. `ability.remove` takes the standing yes back
  at once; it is a make (a file goes), and it is yours only: its callers are the page and the command line.
- The `steps.*` commands that change a pattern or the set (`steps.toggle`, `steps.set`, `steps.write`,
  `steps.paint`, `steps.erase`, `steps.new_track`) are moves: they write
  notes and clips into the Arrangement or make a track. Anthony, 26 November 2026, asked for a step sequencer for
  himself and his controller: the page and the API's callers may use them, and an agent only the reads
  (`steps.tracks`, `steps.sounds`, `steps.read`, `steps.kits`).
- `render.bounce` is a move, and the third move an agent may ask for with no word of yours (AGENT_MAY). Anthony,
  26 November 2026: "The agent thinks it can't run a render. It should know how to bounce tracks and projects. And
  efficiently access the results without pulling them fully into context." It is a move because it takes Live for
  the export, stops playback and leaves a heard reference for Now. It changes no value of the mix, writes only
  new files in the bounce folder, and puts the loop and a heard Pin back, so it saves no version and leaves no
  History row. It can render nothing but the mix and the set's own tracks (never a monitor track), at most four
  files and ten minutes of audio a call. `render.measure` only reads audio files and answers in a few numbers.
- The `song.*` commands that change which song Live has (`song.new`, `song.save`, `song.save_as`, `song.open`)
  are moves, for the person at the page and the command line only (Anthony, 27 November 2026: "we need to build
  song management so we can create new, save, and load projects"). Each saves the song in front first, and the
  desk then follows the song (zpkt.app.songs). `song.list` is a read.
- `steps.focus` is a move though it writes nothing into Live: it says what the sequencer has in hand, and with that
  what the MiniLab's pads will do, under your hands (as `page.arm` does). `steps.loop` moves the transport's loop.
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
    # a batch of changes, checked whole (zpkt.app.change)
    "live.change": "move",
    # a batch that waits for your tap: structure and code (zpkt.app.propose)
    "live.propose.check": "read",
    "live.propose": "move",
    # code you allowed for good (zpkt.app.abilities; the commands are in zpkt.app.propose)
    "ability.list": "read",
    "ability.remove": "make",
    "ability.run": "move",
    # Steps: a pattern on the Song (zpkt.app.steps_commands)
    "steps.tracks": "read",
    "steps.sounds": "read",
    "steps.read": "read",
    "steps.kits": "read",
    "steps.toggle": "move",
    "steps.set": "move",
    "steps.write": "move",
    "steps.paint": "move",
    "steps.erase": "move",
    "steps.new_track": "move",
    "steps.focus": "move",
    "steps.loop": "move",
    # bounce and measure: how an agent hears (zpkt.app.bounce_commands)
    "render.bounce": "move",
    "render.measure": "read",
    # the jobs (zpkt.app.jobs)
    "live.run": "move",
    "live.read": "read",
    "live.open_set": "move",
    "song.list": "read",
    "song.new": "move",
    "song.save": "move",
    "song.save_as": "move",
    "song.open": "move",
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


# The moves an agent may ask for on its own. The docstring above has the reason for each; tests/app/test_effects.py
# writes this set out again.
AGENT_MAY: frozenset[str] = frozenset({"live.change", "ability.run", "render.bounce"})


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
    bus.register(kind, Spec(handler, effect_of(kind), agent_may=kind in AGENT_MAY, **spec))
