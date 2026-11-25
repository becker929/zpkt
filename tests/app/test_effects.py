"""Every command is a read, a make or a move, by one table (zpkt.app.effects). The whole list is written out here, so
a new command, or one whose class changes, fails this test until someone decides and writes it down."""

from __future__ import annotations

import pytest

from zpkt.app import effects
from zpkt.app.bus import Bus, Command, Spec

from .test_song import song_rig  # noqa: F401  (the Song adapter on the rig)

READS = {
    "describe",
    "live.read",
    "measurement.read",
    "options.get",
    "options.list",
    "options.show",
    "page.layout",
    "page.lint",
    "song.list",
    "song.recipe",
    "song.show",
    "state.read",
    "state.take",
}
MAKES = {
    "history.checkpoint",
    "monitor.pin",
    "option.pick",
    "option.propose",
    "options.make",
    "page.draft",
    "page.make",
    "song.delete",
    "song.keep",
    "song.queue",
    "song.save",
    "song.transitions",
    "surface.make",
    "surface.save",
}
MOVES = {
    "history.redo",
    "history.revert",
    "history.undo",
    "live.open_set",
    "live.render_loop",
    "live.run",
    "live.set_tempo",
    "live.transport",
    "mix.reset",
    "mix.set",
    "mix.toggle",
    "monitor.choose",
    "monitor.hear",
    "options.pick",
    "page.apply",
    "page.arm",
    "page.set",
    "pager.restart",
    "song.build",
    "state.put",
    "surface.remove",
    "tempo.scale",
    "tempo.set",
    "transport",
}


def test_the_table_is_exactly_this_list():
    listed = {**dict.fromkeys(READS, "read"), **dict.fromkeys(MAKES, "make"), **dict.fromkeys(MOVES, "move")}
    assert len(listed) == len(READS) + len(MAKES) + len(MOVES)  # no kind in two classes
    assert listed == effects.EFFECTS


def test_every_command_on_the_running_app_has_the_class_the_table_gives(asked, song_rig):  # noqa: F811
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
