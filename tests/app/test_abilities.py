"""Abilities: a proposal's code kept for good after "Always", run again with new arguments and no card, built on
each other with `use`, and used as steps of a batch. On FakeLive, through the bus."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tests.app.test_live_change import KICK, VOL
from tests.app.test_live_propose import whole
from zpkt.app import abilities, coderun
from zpkt.app.bus import Command
from zpkt.live import chain, newtrack

CONTRACT = Path(__file__).resolve().parents[2] / "lib" / "contracts" / "ability.schema.json"
BPM = {"bpm": {"type": "number", "description": "the tempo, in BPM"}}
SET_TEMPO = {
    "code": "song.tempo = args['bpm']\nresult = {'tempo': args['bpm']}",
    "does": "Sets the tempo.",
    "name": "set_tempo",
    "params": BPM,
    "args": {"bpm": 91.0},
}
READ_TEMPO = {"code": "result = {'tempo': song.tempo}", "does": "Reads the tempo.", "name": "read_tempo"}
DOUBLE = {
    "code": "r = use('set_tempo', {'bpm': args['bpm'] * 2})\nresult = {'doubled_to': r['tempo']}",
    "does": "Sets the tempo to twice a number.",
    "name": "double_tempo",
    "params": BPM,
    "args": {"bpm": 50.0},
}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    monkeypatch.setattr(newtrack.time, "sleep", lambda s: None)


def batch(*steps, why="an ability"):
    return {"why": why, "steps": list(steps)}


def check(rig, args):
    return rig.desk.bus.submit(Command("live.propose.check", "agent", args))


def propose(rig, args, always=False, group="ask-s1"):
    """What the Ask gate sends after the tap: the person's word, and `always` after that button."""
    sent = {**args, "always": True} if always else args
    return rig.desk.bus.submit(Command("live.propose", "agent", sent, approval="user", group=group))


def keep(rig, *steps):
    code, reply = propose(rig, batch(*steps), always=True)
    assert code == 200 and not reply["not_saved"], reply
    return reply


def run(rig, name, args=None, who="agent", **kw):
    return rig.desk.bus.submit(Command("ability.run", who, {"name": name, "args": args or {}}, **kw))


def rows(rig):
    return [e for e in rig.desk.history.entries if e["k"] == "change"]


# ---- kept on "Always", and only then -------------------------------------------------------------------------------


def test_always_keeps_each_code_step_that_ran_and_do_it_keeps_nothing(rig):
    store = rig.desk.abilities
    code, reply = propose(rig, batch(SET_TEMPO))  # "Do it"
    assert code == 200 and "abilities" not in reply and store.all() == [] and rig.live.song.tempo == 91.0
    code, reply = propose(
        rig, batch({**SET_TEMPO, "args": {"bpm": 120}}, {"set": VOL, "to": 0.5}, READ_TEMPO), always=True
    )
    assert code == 200 and reply["done"] == 3, reply
    assert reply["abilities"] == [{"name": "set_tempo", "replaced": False}, {"name": "read_tempo", "replaced": False}]
    assert reply["not_saved"] == [] and rig.live.song.tempo == 120.0
    assert store.names() == ["read_tempo", "set_tempo"]
    file = rig.desk.settings.abilities_dir / "set_tempo.json"
    kept = json.loads(file.read_text())
    assert kept["code"] == SET_TEMPO["code"] and kept["does"] == "Sets the tempo." and kept["params"] == BPM
    assert kept["session"] == "s1" and kept["runs"] == 0 and kept["last_run"] is None and kept["made"].endswith("Z")
    jsonschema.validate(kept, json.loads(CONTRACT.read_text()))
    assert rig.desk.settings.abilities_dir == rig.tmp / "sets" / "abilities"  # the rig's folder, not the set's


def test_an_agent_cannot_say_always_for_itself(rig):
    """`always` counts only on a command that carries the person's word; an agent's own never reaches one."""
    code, reply = rig.desk.bus.submit(Command("live.propose", "agent", {**batch(SET_TEMPO), "always": True}))
    assert code == 403 and "cannot change Live" in reply["error"] and rig.desk.abilities.all() == []
    code, reply = check(rig, {**batch(SET_TEMPO), "always": True})
    assert code == 200 and rig.desk.abilities.all() == []


def test_a_code_step_that_failed_or_did_not_run_is_not_kept(rig):
    broken = {"code": "raise ValueError('no')", "does": "Breaks.", "name": "breaks"}
    code, reply = propose(rig, batch(READ_TEMPO, broken, SET_TEMPO), always=True)
    assert code == 502 and reply["abilities"] == [{"name": "read_tempo", "replaced": False}]
    assert reply["not_saved"] == [
        {"name": "breaks", "why": "Live reported an error"},
        {"name": "set_tempo", "why": "it did not run"},
    ]
    assert rig.desk.abilities.names() == ["read_tempo"]


def test_a_name_is_made_from_the_sentence_when_none_is_given_and_never_takes_anothers_place(rig):
    step = {"code": "result = song.tempo", "does": "Reads the tempo, now."}
    assert keep(rig, step)["abilities"] == [{"name": "reads_the_tempo_now", "replaced": False}]
    assert keep(rig, step)["abilities"] == [{"name": "reads_the_tempo_now_2", "replaced": False}]
    code, reply = check(rig, batch(step, step))
    assert [s["name"] for s in reply["steps"]] == ["reads_the_tempo_now_3", "reads_the_tempo_now_4"]
    code, reply = check(rig, batch(SET_TEMPO, SET_TEMPO))
    assert code == 400 and 'also named "set_tempo"' in reply["problems"][0]
    for bad in ("Set Tempo", "9lives", "x" * 41, 7):
        code, reply = check(rig, batch({**SET_TEMPO, "name": bad}))
        assert code == 400 and "snake_case" in reply["problems"][0], bad
    assert abilities.slug("91 BPM!") == "do_91_bpm" and abilities.slug("...") == "ability"


def test_replacing_an_ability_takes_a_new_always_and_the_card_says_what_it_replaces(rig):
    keep(rig, SET_TEMPO)
    keep(rig, DOUBLE)  # in a batch of its own: what it uses must be kept already
    louder = {**SET_TEMPO, "code": "song.tempo = args['bpm'] + 1\nresult = {'tempo': args['bpm'] + 1}"}
    code, card = check(rig, batch(louder))
    step = card["steps"][0]
    assert step["replaces"] is True and step["used_by"] == 1 and step["name"] == "set_tempo" and card["always"]
    code, reply = propose(rig, batch(louder))  # "Do it": it runs once, and the kept one is as it was
    assert code == 200 and rig.live.song.tempo == 92.0
    assert rig.desk.abilities.get("set_tempo")["code"] == SET_TEMPO["code"]
    code, reply = propose(rig, batch(louder), always=True)
    assert reply["abilities"] == [{"name": "set_tempo", "replaced": True}]
    assert rig.desk.abilities.get("set_tempo")["code"] == louder["code"]
    code, reply = run(rig, "double_tempo", {"bpm": 40})  # what uses it now does the new thing
    assert code == 200 and reply["result"] == {"doubled_to": 81.0} and rig.live.song.tempo == 81.0


def test_a_replacement_may_not_break_what_uses_the_ability(rig):
    keep(rig, SET_TEMPO)
    keep(rig, {**DOUBLE, "code": "result = use('set_tempo', {'bpm': 100})", "params": {}, "args": {}})
    renamed = {
        "code": "song.tempo = args['tempo']",
        "does": "Sets the tempo.",
        "name": "set_tempo",
        "params": {"tempo": {"type": "number", "description": "the tempo, in BPM"}},
        "args": {"tempo": 91},
    }
    code, reply = check(rig, batch(renamed))
    assert (
        code == 400
        and 'would break "double_tempo"' in reply["problems"][0]
        and "args lacks tempo" in reply["problems"][0]
    )
    wider = {**SET_TEMPO, "code": "song.tempo = args['bpm'] * args['times']"}
    wider["params"] = {**BPM, "times": {"type": "integer", "description": "times the number", "default": 1}}
    assert check(rig, batch(wider))[0] == 200  # a new parameter with a default breaks nobody


def test_at_most_fifty_abilities(rig):
    store = rig.desk.abilities
    for k in range(abilities.MAX):
        store.save(f"a{k}", "Reads.", {}, "result = 1")
    code, card = check(rig, batch(SET_TEMPO))
    assert code == 200 and card["always"] is False  # no room: the card has no "Always"
    code, reply = propose(rig, batch(SET_TEMPO), always=True)
    assert code == 200 and reply["abilities"] == [] and "50 abilities already" in reply["not_saved"][0]["why"]
    code, card = check(rig, batch({**SET_TEMPO, "name": "a3"}))
    assert card["always"] is True and card["steps"][0]["replaces"]  # a replacement adds none
    with pytest.raises(abilities.Full):
        store.save("one_more", "Reads.", {}, "result = 1")
    assert len(store.all()) == 50


# ---- parameters and arguments --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"args": {}}, "args lacks bpm"),
        ({"args": {"bpm": "fast"}}, "bpm must be a number"),
        ({"args": {"bpm": True}}, "bpm must be a number"),
        ({"args": {"bpm": 91, "swing": 1}}, "swing, which is not a parameter"),
        ({"args": [91]}, '"args" is an object'),
        ({"params": {"bpm": {"type": "tempo", "description": "x"}}}, 'needs "type"'),
        ({"params": {"bpm": {"type": "number"}}}, 'needs "description"'),
        ({"params": {"BPM": {"type": "number", "description": "x"}}}, "snake_case"),
        ({"params": [1]}, '"params" is an object'),
        ({"params": {**BPM, "unit": {"type": "string", "description": "never read"}}, "args": {"bpm": 1, "unit": "x"}},
         "unit is declared but not used"),
        ({"params": {"bpm": {**BPM["bpm"], "enum": [90, 120]}}, "args": {"bpm": 91}}, "must be one of [90, 120]"),
        ({"params": {"bpm": {**BPM["bpm"], "default": "x"}}}, 'the "default" of "bpm" must be a number'),
        ({"params": {"bpm": {**BPM["bpm"], "enum": []}}}, '"enum" of "bpm" is a list of 1 to 20'),
        ({"params": {f"p{k}": {"type": "number", "description": "x"} for k in range(9)}}, "9 parameters is more than 8"),
    ],
    ids=lambda v: str(v)[:40],
)  # fmt: skip
def test_a_proposal_whose_parameters_or_arguments_do_not_fit_is_refused(rig, change, words):
    code, reply = check(rig, batch({**SET_TEMPO, **change}))
    assert code == 400 and words in reply["problems"][0], reply
    assert rig.live.song.tempo != 91.0


def test_a_default_fills_in_and_an_integer_is_an_int(rig):
    step = {
        "code": "result = [args['bars'], args['mode'], args['loud']]",
        "does": "Echoes its arguments.",
        "name": "echo",
        "params": {
            "bars": {"type": "integer", "description": "how many bars", "default": 4},
            "mode": {"type": "string", "description": "which way", "enum": ["up", "down"], "default": "up"},
            "loud": {"type": "boolean", "description": "louder or not"},
        },
        "args": {"loud": True},
    }
    code, card = check(rig, batch(step))
    assert code == 200 and card["steps"][0]["args"] == [["bars", 4], ["mode", "up"], ["loud", True]]
    keep(rig, step)
    code, reply = run(rig, "echo", {"loud": False, "bars": 8.0})
    assert code == 200 and reply["result"] == [8, "up", False]
    for args, words in (
        ({}, "args lacks loud"),
        ({"loud": True, "mode": "sideways"}, 'must be one of ["up", "down"]'),
        ({"loud": True, "bars": 2.5}, "bars must be a integer"),
        ({"loud": 1}, "loud must be a boolean"),
    ):
        code, reply = run(rig, "echo", args)
        assert code == 400 and words in reply["error"] and "nothing changed" in reply["error"], reply


def test_arguments_are_data_and_never_become_code(rig):
    step = {
        "code": "result = args['name']",
        "does": "Echoes a name.",
        "name": "echo_name",
        "params": {"name": {"type": "string", "description": "any text"}},
        "args": {"name": "x"},
    }
    keep(rig, step)
    tempo = rig.live.song.tempo
    for evil in (
        '"); song.tempo = 5.0 #',
        "' + str(setattr(song, 'tempo', 5.0)) + '",
        "\\'\nsong.tempo = 5.0\n",
        "\u2603",
    ):
        code, reply = run(rig, "echo_name", {"name": evil})
        assert code == 200 and reply["result"] == evil and rig.live.song.tempo == tempo, evil
    text = abilities.program("result = args['name']", {"name": '"); song.tempo = 5.0 #'})
    assert text.splitlines()[0].startswith("args = __import__('json').loads(") and text.count("\n") == 1


# ---- running one: no card, the same checks, History ----------------------------------------------------------------


def test_a_run_is_one_history_row_with_a_version_before_it_and_undo_leaves_it(rig):
    keep(rig, SET_TEMPO)
    before = len(rig.desk.history.entries)
    code, reply = run(rig, "set_tempo", {"bpm": 133}, group="ask-s2")
    assert code == 200 and reply == {
        "ok": True,
        "name": "set_tempo",
        "result": {"tempo": 133},
        "no_undo": ['Ran set_tempo(bpm=133)'],
    }  # fmt: skip
    assert rig.live.song.tempo == 133.0
    cp, row = rig.desk.history.entries[before:]
    assert cp["k"] == "checkpoint" and cp["who"] == "sys" and cp["name"].startswith("before-ask-s2")
    assert row["k"] == "change" and row["who"] == "agent" and row["why"] == "set_tempo(bpm=133)"
    assert row["moves"] == [] and row["devices"] == []
    (stays,) = row["stays"]
    assert stays["op"] == "code" and stays["ability"] == "set_tempo" and stays["args"] == {"bpm": 133}
    kept = rig.desk.abilities.get("set_tempo")
    assert kept["runs"] == 1 and kept["last_run"].endswith("Z")
    assert rig.desk.bus.table["ability.run"].agent_may and rig.desk.bus.log[-1]["status"] == 200
    code, undone = rig.command("history.undo")
    assert code == 200 and undone["left"] == ["Ran set_tempo(bpm=133)"] and rig.live.song.tempo == 133.0


def test_an_ability_that_only_reads_leaves_no_row_and_no_version(rig):
    keep(rig, READ_TEMPO)
    entries = len(rig.desk.history.entries)
    code, reply = run(rig, "read_tempo")
    assert code == 200 and reply == {"ok": True, "name": "read_tempo", "result": {"tempo": rig.live.song.tempo}}
    assert len(rig.desk.history.entries) == entries and rig.desk.abilities.get("read_tempo")["runs"] == 1
    listed = {a["name"]: a for a in rig.desk.bus.submit(Command("ability.list", "agent"))[1]["abilities"]}
    assert listed["read_tempo"]["reads"] is True


def test_a_failing_run_says_part_of_it_may_have_run(rig):
    keep(
        rig,
        {
            **SET_TEMPO,
            "name": "half",
            "code": "song.tempo = args['bpm']\nif args['bpm'] > 200:\n    raise ValueError('too fast')",
        },
    )
    code, reply = run(rig, "half", {"bpm": 250})
    assert code == 502 and reply["ok"] is False and "too fast" in reply["error"]
    assert "part of the code may have run" in reply["error"] and rig.live.song.tempo == 250.0
    row = rows(rig)[-1]
    assert row["stays"][0]["failed"] is True and "may have run" in row["stays"][0]["words"]


def test_a_removed_ability_is_gone_at_once_and_only_the_person_removes(rig):
    keep(rig, SET_TEMPO)
    code, reply = rig.desk.bus.submit(Command("ability.remove", "agent", {"name": "set_tempo"}))
    assert code == 403 and "not open to 'agent'" in reply["error"] and rig.desk.abilities.names() == ["set_tempo"]
    code, reply = rig.command("ability.remove", {"name": "set_tempo"})  # the page: the person
    assert code == 200 and reply == {"ok": True, "removed": "set_tempo", "broken": []}
    assert rig.desk.abilities.all() == []
    assert len(list((rig.desk.settings.abilities_dir / "removed").glob("set_tempo-*.json"))) == 1  # kept, not lost
    tempo = rig.live.song.tempo
    code, reply = run(rig, "set_tempo", {"bpm": 99})
    assert code == 404 and "no ability" in reply["error"] and "propose its code again" in reply["error"]
    assert rig.live.song.tempo == tempo
    assert rig.command("ability.remove", {"name": "set_tempo"})[0] == 404
    assert rig.command("ability.run", {"name": "x"})[0] == 403  # the page runs no code in Live, kept or not


def test_the_rails_hold_on_every_run(rig):
    step = {
        "code": "find_track(args['track']).mute = True",
        "does": "Mutes a track.",
        "name": "mute_track",
        "params": {"track": {"type": "string", "description": "the track's name"}},
        "args": {"track": "kick"},
    }
    code, reply = check(rig, batch({**step, "args": {"track": "mon A"}}))
    assert code == 400 and "monitor track" in reply["problems"][0]
    keep(rig, step)
    before = whole(rig)
    for name in ("mon A", "Mon b", "zpkt listen"):
        code, reply = run(rig, "mute_track", {"track": name})
        assert code == 400 and "the app never changes those" in reply["error"], name
    file = rig.desk.settings.abilities_dir / "mute_track.json"  # a file changed by hand to name a monitor track
    kept = json.loads(file.read_text())
    file.write_text(json.dumps({**kept, "code": "find_track('mon A').mute = False"}))
    code, reply = run(rig, "mute_track", {"track": "kick"})
    assert code == 400 and "monitor track" in reply["error"]
    file.write_text(json.dumps({**kept, "code": "this is ( not python"}))
    assert run(rig, "mute_track", {"track": "kick"})[0] == 400
    assert whole(rig) == before


def test_the_wrong_set_holds_a_run(rig):
    keep(rig, SET_TEMPO)
    rig.live.song.file_path = "/Sets/other Project/someone_elses_set.als"
    rig.desk.bus.guard.forget()
    code, reply = run(rig, "set_tempo", {"bpm": 99})
    assert code == 409 and "someone_elses_set" in reply["error"] and rig.live.song.tempo == 91.0


# ---- chaining: abilities built from abilities ------------------------------------------------------------------


def test_use_runs_another_ability_in_the_same_call_and_gives_its_result(rig):
    keep(rig, SET_TEMPO)
    code, card = check(rig, batch(DOUBLE))
    assert code == 200 and card["steps"][0]["uses"] == ["set_tempo"]
    calls = len(rig.live.calls)
    keep(rig, DOUBLE)
    assert rig.live.song.tempo == 100.0
    calls = len(rig.live.calls)
    code, reply = run(rig, "double_tempo", {"bpm": 60})
    assert code == 200 and reply["result"] == {"doubled_to": 120.0} and rig.live.song.tempo == 120.0
    sent = [c.code for c in rig.live.calls[calls:] if "double" in c.code or "_zp" in c.code]
    assert len(sent) == 1 and "def use(" in sent[0]  # the one it uses went along: one call to Live
    row = rows(rig)[-1]
    assert row["why"] == "double_tempo(bpm=60)" and row["stays"][0]["uses"] == ["set_tempo"]
    listed = {a["name"]: a for a in rig.desk.bus.submit(Command("ability.list", "you"))[1]["abilities"]}
    assert listed["double_tempo"]["uses"] == ["set_tempo"] and listed["set_tempo"]["used_by"] == ["double_tempo"]
    assert listed["double_tempo"]["reads"] is False  # it only calls, but what it calls writes


def test_each_used_ability_has_its_own_args_and_the_callers_names_do_not_leak(rig):
    keep(rig, {"code": "result = [args['x'], 'secret' in globals()]", "does": "Looks.", "name": "look",
               "params": {"x": {"type": "integer", "description": "any"}}, "args": {"x": 1}})  # fmt: skip
    step = {"code": "secret = 1\nresult = [use('look', {'x': 2}), args['x'], use('look', {'x': 3})]",
            "does": "Looks twice.", "name": "look_twice",
            "params": {"x": {"type": "integer", "description": "any"}}, "args": {"x": 9}}  # fmt: skip
    code, reply = propose(rig, batch(step))
    assert code == 200 and reply["ran"][0]["result"] == [[2, False], 9, [3, False]]


@pytest.mark.parametrize(
    ("code", "words"),
    [
        ("result = use('nobody', {})", 'there is no ability "nobody"'),
        ("n = 'set_tempo'\nresult = use(n, {})", "name written out"),
        ("result = use('set_tempo')", 'use("set_tempo"): args lacks bpm'),
        ("result = use('set_tempo', {'bpm': 'fast'})", 'use("set_tempo"): bpm must be a number'),
        ("result = use('set_tempo', {'bpm': 1}, 2)", "name written out"),
        ("result = use('loop_a', {})", "in a circle: loop_a uses loop_a"),
    ],
)
def test_what_a_proposal_uses_is_checked_before_anybody_is_asked(rig, code, words):
    keep(rig, SET_TEMPO)
    reply = check(rig, batch({"code": code, "does": "Uses something.", "name": "loop_a"}))
    assert reply[0] == 400 and words in reply[1]["problems"][0], reply


def test_a_circle_and_a_chain_that_is_too_deep_are_refused(rig):
    store = rig.desk.abilities
    store.save("a", "A.", {}, "result = use('b', {})")
    store.save("b", "B.", {}, "result = 1")
    code, reply = check(rig, batch({"code": "result = use('a', {})", "does": "B again.", "name": "b"}))
    assert code == 400 and "in a circle: a uses b" in reply["problems"][0]
    for k in range(1, 6):
        store.save(f"d{k}", "Deep.", {}, f"result = use('d{k + 1}', {{}})" if k < 5 else "result = 5")
    code, reply = check(rig, batch({"code": "result = use('d2', {})", "does": "Four deep.", "name": "top"}))
    assert code == 200 and reply["steps"][0]["uses"] == ["d2"]
    code, reply = propose(rig, batch({"code": "result = use('d1', {})", "does": "Five deep.", "name": "top"}))
    assert code == 200 and reply["ran"][0]["result"] == 5
    store.save("d5", "Deeper.", {}, "result = use('b', {})")
    code, reply = check(rig, batch({"code": "result = use('d1', {})", "does": "Six deep.", "name": "top"}))
    assert code == 400 and "deeper than 5" in reply["problems"][0]
    assert run(rig, "d1") == (200, {"ok": True, "name": "d1", "result": 1})  # five uses deep is the most
    store.save("b", "B.", {}, "result = use('c', {})")
    store.save("c", "C.", {}, "result = 2")
    assert run(rig, "d1")[0] == 400 and "deeper than 5" in run(rig, "d1")[1]["error"]


def test_removing_what_another_uses_breaks_the_caller_and_says_so(rig):
    keep(rig, SET_TEMPO)
    keep(rig, DOUBLE)  # in a batch of its own: what it uses must be kept already
    code, reply = rig.command("ability.remove", {"name": "set_tempo"})
    assert code == 200 and reply["broken"] == ["double_tempo"]
    listed = rig.desk.bus.submit(Command("ability.list", "you"))[1]["abilities"]
    assert [(a["name"], a["missing"]) for a in listed] == [("double_tempo", ["set_tempo"])]
    tempo = rig.live.song.tempo
    code, reply = run(rig, "double_tempo", {"bpm": 70})
    assert code == 400 and 'no ability "set_tempo"' in reply["error"] and "proposed again" in reply["error"]
    assert rig.live.song.tempo == tempo
    keep(rig, SET_TEMPO)  # proposed again, with a new tap: the caller works again
    assert run(rig, "double_tempo", {"bpm": 70})[0] == 200 and rig.live.song.tempo == 140.0


def test_what_one_ability_hands_another_is_checked_in_live_too(rig):
    keep(rig, {"code": "find_track(args['track']).mute = True", "does": "Mutes a track.", "name": "mute_track",
               "params": {"track": {"type": "string", "description": "the track"}}, "args": {"track": "kick"}})  # fmt: skip
    caller = {"code": "result = use('mute_track', {'track': args['prefix'] + ' A'})", "does": "Mutes by prefix.",
              "name": "mute_by_prefix", "params": {"prefix": {"type": "string", "description": "the start"}},
              "args": {"prefix": "p2-rd"}}  # fmt: skip
    code, reply = propose(rig, batch({**caller, "args": {"prefix": "mo" + "n"}}))  # "mon A" is made inside Live
    assert code == 502 and "the app never changes that" in reply["failed"]["why"], reply
    assert rig.track("mon A").mute is True  # as the desk left it: the fake set's monitor tracks are muted
    code, reply = propose(rig, batch({"code": "result = use('mute_track', {'track': 7})", "does": "Wrong type.",
                                      "name": "wrong"}))  # fmt: skip
    assert code == 400 and "track must be a string" in reply["problems"][0]


# ---- an ability as a step of a batch ---------------------------------------------------------------------------


def test_a_use_step_runs_in_a_change_batch_with_no_tap_and_is_code_to_history(rig):
    keep(rig, SET_TEMPO, READ_TEMPO)
    steps = [
        {"set": VOL, "to": 0.5},
        {"use": "set_tempo", "args": {"bpm": 150}},
        {"use": "read_tempo"},
        {"device": "desk Glue", "track": KICK, "on": False},
    ]
    code, reply = rig.desk.bus.submit(Command("live.change", "agent", {"why": "faster", "steps": steps}))
    assert code == 200 and reply["done"] == 4, reply
    assert rig.live.song.tempo == 150.0 and rig.track(KICK).mixer_device.volume.value == 0.5
    assert reply["ran"] == [
        {"step": 2, "ok": True, "result": {"tempo": 150}, "ability": "set_tempo"},
        {"step": 3, "ok": True, "result": {"tempo": 150.0}, "ability": "read_tempo"},
    ]
    assert reply["undo"] == "faster (2 controls)" and reply["no_undo"] == ["Ran set_tempo(bpm=150)"]
    row = rows(rig)[-1]
    assert [s["ability"] for s in row["stays"]] == ["set_tempo"]  # the one that only reads left nothing
    code, undone = rig.command("history.undo")
    assert undone["left"] == ["Ran set_tempo(bpm=150)"] and rig.live.song.tempo == 150.0
    assert rig.track(KICK).mixer_device.volume.value != 0.5  # the values are taken back


def test_a_use_step_is_checked_with_the_batch(rig):
    keep(rig, SET_TEMPO)
    before = whole(rig)
    bad = [
        {"set": VOL, "to": 0.5},
        {"use": "nobody"},
        {"use": "set_tempo", "args": {"bpm": "fast"}},
        {"use": "set_tempo"},
        {"use": "Set Tempo"},
        {"use": "set_tempo", "args": [1]},
    ]
    code, reply = rig.desk.bus.submit(Command("live.change", "agent", {"why": "bad", "steps": bad}))
    assert code == 400 and [int(p.split()[1].rstrip(":")) for p in reply["problems"]] == [5, 6, 2, 3, 4], reply
    text = "\n".join(reply["problems"])
    for words in ('no ability "nobody"', "bpm must be a number", "args lacks bpm", "snake_case", '"args" is an object'):
        assert words in text, words
    assert whole(rig) == before and rows(rig)[-1]["why"] == "an ability"
    many = [{"use": "set_tempo", "args": {"bpm": 100 + k}} for k in range(9)]
    code, reply = rig.desk.bus.submit(Command("live.change", "agent", {"why": "many", "steps": many}))
    assert code == 400 and "9 abilities used is more than 8" in reply["problems"][0]
    code, reply = rig.desk.bus.submit(Command("live.change", "agent", {"why": "code", "steps": [SET_TEMPO]}))
    assert code == 400  # live.change still takes no code of its own: only what was kept


def test_a_batch_of_only_reading_abilities_leaves_no_row(rig):
    keep(rig, READ_TEMPO)
    entries = len(rig.desk.history.entries)
    code, reply = rig.desk.bus.submit(Command("live.change", "agent", batch({"use": "read_tempo"}, why="look")))
    assert code == 200 and reply["ran"][0]["result"] == {"tempo": rig.live.song.tempo} and reply["undo"] is None
    assert len(rig.desk.history.entries) == entries


def test_a_use_step_in_a_proposal_is_a_line_on_the_card(rig):
    keep(rig, SET_TEMPO, READ_TEMPO)
    code, card = check(rig, batch({"use": "set_tempo", "args": {"bpm": 77}}, {"use": "read_tempo"}))
    assert code == 200 and card["always"] is False  # nothing new to keep
    assert card["steps"] == [
        {"n": 1, "text": "Run set_tempo(bpm=77)", "no_undo": True},
        {"n": 2, "text": "Run read_tempo()"},
    ]
    code, reply = propose(rig, batch({"use": "set_tempo", "args": {"bpm": 77}}))
    assert code == 200 and rig.live.song.tempo == 77.0 and reply["no_undo"] == ["Ran set_tempo(bpm=77)"]


# ---- hints: few, well-shaped abilities ------------------------------------------------------------------------


def test_hints_go_to_the_agent_and_not_onto_the_card(rig):
    keep(rig, SET_TEMPO)
    literal = {"code": "find_track('kick').mute = True", "does": "Mutes the kick."}
    code, card = check(rig, batch(literal))
    assert code == 200 and len(card["hints"]) == 1
    assert 'spells out "kick", a track of this set' in card["hints"][0] and "parameter" in card["hints"][0]
    assert "hints" not in json.dumps(card["steps"])
    again = {**SET_TEMPO, "name": "set_tempo_2"}
    same = {**SET_TEMPO, "name": "change_bpm"}
    for step in (again, same):
        code, card = check(rig, batch(step))
        assert code == 200 and 'the ability "set_tempo" looks like this one' in card["hints"][0], step["name"]
        assert "ability_set_tempo" in card["hints"][0]
    code, reply = propose(rig, batch(literal))
    assert code == 200 and reply["hints"] == check(rig, batch(literal))[1]["hints"]
    fine = {"code": "find_track(args['track']).mute = True\nresult = 'desk EQ'", "does": "Mutes a track.",
            "params": {"track": {"type": "string", "description": "the track"}}, "args": {"track": "kick"}}  # fmt: skip
    assert "hints" not in check(rig, batch(fine))[1]  # it has a text parameter: nothing to say
    assert "hints" not in check(rig, batch(SET_TEMPO))[1]  # the same name is a replacement, not a second one


# ---- the rules alone -----------------------------------------------------------------------------------------------


def test_the_store_passes_over_files_that_are_not_abilities(tmp_path):
    store = abilities.Store(tmp_path, clock=lambda: 0.0)
    store.save("good", "Reads.", {}, "result = 1", "s9")
    (tmp_path / "bad.json").write_text("{not json")
    (tmp_path / "other.json").write_text(json.dumps({"name": "mismatch", "does": "x", "code": "x"}))
    (tmp_path / "Bad Name.json").write_text(json.dumps({"name": "Bad Name", "does": "x", "code": "x"}))
    (tmp_path / "noparams.json").write_text(json.dumps({"name": "noparams", "does": "x", "code": "x", "params": [1]}))
    assert store.names() == ["good"] and store.get("good")["made"] == "1970-01-01T00:00:00Z"
    assert store.get("../good") is None and store.get(7) is None and store.remove("nobody") is False
    assert abilities.free_name("a", ["a", "a_2"]) == "a_3" and len(abilities.free_name("x" * 40, ["x" * 40])) == 40


def test_reading_code_for_what_it_reads_and_uses():
    import ast

    tree = ast.parse(
        "a = args['x']\nb = args.get('y', 1)\nc = args[k]\nuse('one', {'p': 1})\nuse('two', {'p': a})\nuse('one')"
    )
    assert abilities.reads(tree) == {"x", "y"}
    assert abilities.calls(tree) == [("one", {"p": 1}), ("two", None), ("one", {})]
    assert abilities.used("use('one', {})\nuse('two', {})\nuse('one', {})") == ["one", "two"]
    assert coderun.literals(ast.parse("x = 'a'; y = 'b'; z = 'a'")) == ["a", "b"]
    assert (
        abilities.call_words("f", {"s": "x" * 100}).endswith("…)")
        and len(abilities.call_words("f", {"s": "x" * 100})) < 70
    )
