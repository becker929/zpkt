"""Every command is a read, a make or a move, by one table (zpkt.app.effects). The whole list is written out here, so
a new command, or one whose class changes, fails this test until someone decides and writes it down."""

from __future__ import annotations

import pytest

from zpkt.app import effects
from zpkt.app.bus import Bus, Command, Spec

READS = {
    "ability.list",
    "arrangement.read",
    "describe",
    "live.propose.check",
    "live.read",
    "measurement.read",
    "mix.describe",
    "page.layout",
    "page.lint",
    "page.list",
    "desk.state",
    "state.read",
    "state.take",
    "steps.kits",
    "steps.read",
    "steps.sounds",
    "steps.tracks",
}
MAKES = {
    "ability.remove",
    "history.checkpoint",
    "monitor.pin",
    "page.draft",
    "page.make",
    "surface.make",
    "surface.save",
}
MOVES = {
    "ability.run",
    "history.back",
    "history.redo",
    "history.revert",
    "history.undo",
    "live.change",
    "live.open_set",
    "live.propose",
    "live.render_loop",
    "live.run",
    "live.set_tempo",
    "live.transport",
    "meter.install",
    "mix.reset",
    "mix.set",
    "mix.toggle",
    "monitor.choose",
    "monitor.hear",
    "page.apply",
    "panel.apply",
    "page.arm",
    "page.compare",
    "page.open",
    "page.organize",
    "page.set",
    "pager.restart",
    "state.put",
    "steps.focus",
    "steps.loop",
    "steps.new_track",
    "steps.toggle",
    "surface.remove",
    "tempo.scale",
    "tempo.set",
    "transport",
}


# The moves an agent may ask for with no word of the user's. One, by Anthony's decision of 26 November 2026: a batch
# of value and device steps, checked whole, undone as one (zpkt.app.change). Adding a kind here is a decision.
# `live.propose` (structure and code) is NOT here: it needs the person's tap (zpkt.app.propose).
# `ability.run`, by his decision of the same day ("an 'Always' button which adds the code to an auto allowed set"):
# it runs only code the person kept with "Always" on a card, so the word was given before (zpkt.app.abilities).
AGENT_MAY = {"live.change", "ability.run"}


def test_an_agent_may_make_exactly_these_moves_on_its_own(asked):
    assert effects.AGENT_MAY == AGENT_MAY and AGENT_MAY <= MOVES
    table = asked.rig.desk.bus.table
    assert {kind for kind, spec in table.items() if spec.agent_may} == AGENT_MAY
    for kind in sorted(MOVES - AGENT_MAY):
        code, body = asked.rig.desk.bus.submit(Command(kind, "agent", {}))
        assert code == 403 and "cannot change Live" in body["error"], kind


def test_the_table_is_exactly_this_list():
    listed = {**dict.fromkeys(READS, "read"), **dict.fromkeys(MAKES, "make"), **dict.fromkeys(MOVES, "move")}
    assert len(listed) == len(READS) + len(MAKES) + len(MOVES)  # no kind in two classes
    assert listed == effects.EFFECTS


def test_every_command_on_the_running_app_has_the_class_the_table_gives(asked):
    """The whole app: the desk's commands, the jobs, the agents' and the Song's."""
    table = asked.rig.desk.bus.table
    assert set(table) == set(effects.EFFECTS)
    assert {kind: spec.effect for kind, spec in table.items()} == effects.EFFECTS


def test_reloading_the_pager_and_arming_a_page_are_moves(rig):
    """They change what Live's pager and the MiniLab's controls do, so an agent needs your word and the wrong-set
    guard holds them."""
    for kind, args in (("pager.restart", {}), ("page.arm", {"page": 0})):
        code, body = rig.desk.bus.submit(Command(kind, "agent", args))
        assert code == 403 and "cannot change Live" in body["error"], kind
        assert rig.desk.bus.submit(Command(kind, "you", args))[0] == 200, kind


def test_a_kind_the_table_does_not_have_cannot_be_classed():
    with pytest.raises(ValueError, match=r"zpkt\.app\.effects"):
        effects.effect_of("brand.new")


def test_registering_by_the_table_takes_the_class_from_it():
    bus = Bus()
    effects.register(bus, "mix.set", lambda cmd: (200, {}))
    assert bus.table["mix.set"] == Spec(bus.table["mix.set"].handler, "move")
    with pytest.raises(ValueError, match=r"brand\.new"):
        effects.register(bus, "brand.new", lambda cmd: (200, {}))
