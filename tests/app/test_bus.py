"""The command bus on its own: the dispatch table and the checks, with plain functions as handlers (no Live)."""

from __future__ import annotations

import threading

import pytest

from zpkt.app.bus import BadRequest, Bus, Command, Refused, SetGuard, Spec
from zpkt.app.connections import LiveBusy, LiveConnections
from zpkt.live.transport import LiveError


def ok(cmd: Command):
    return 200, {"ok": True, "who": cmd.who, "group": cmd.group}


def bus_with(effect="move", guard=None, version=None, lock=None, handler=ok):
    bus = Bus(guard=guard, lock=lock, version_before=version, clock=lambda: 100.0)
    bus.register("x.do", Spec(handler, effect, touches_live=lock is not None))
    return bus


def test_a_command_runs_its_handler_and_is_logged_with_who():
    bus = bus_with()
    code, reply = bus.submit(Command("x.do", "minilab"))
    assert code == 200 and reply["who"] == "minilab"
    assert bus.log[-1] == {"at": 100.0, "kind": "x.do", "who": "minilab", "status": 200, "group": None}


def test_an_unknown_kind_is_a_404_that_lists_the_known_ones():
    code, reply = bus_with().submit(Command("nope"))
    assert code == 404 and "x.do" in reply["error"]


def test_who_must_be_one_of_the_seven():
    bus = bus_with()
    for who in ("you", "minilab", "agent", "booth", "demo", "cli", "sys"):
        assert bus.submit(Command("x.do", who, approval="user"))[0] == 200
    code, reply = bus.submit(Command("x.do", "gemini"))  # type: ignore[arg-type]
    assert code == 400 and "gemini" in reply["error"]


def test_a_register_twice_is_an_error():
    bus = bus_with()
    with pytest.raises(ValueError, match="already registered"):
        bus.register("x.do", Spec(ok))


def test_an_agent_may_read_and_make_but_not_move_without_your_word():
    for effect in ("read", "make"):
        assert bus_with(effect).submit(Command("x.do", "agent"))[0] == 200
    code, reply = bus_with("move").submit(Command("x.do", "agent"))
    assert code == 403 and "compare state" in reply["error"] and "Option" not in reply["error"]


def test_only_the_users_word_lets_an_agent_move():
    bus = bus_with("move")
    assert bus.submit(Command("x.do", "agent", approval="user"))[0] == 200
    assert bus.submit(Command("x.do", "agent", approval="option:kick-sub-38"))[0] == 403  # Options are gone
    assert bus.submit(Command("x.do", "agent", approval="because i said so"))[0] == 403


def test_other_hands_need_no_approval_to_move():
    for who in ("you", "minilab", "booth", "demo", "cli"):
        assert bus_with("move").submit(Command("x.do", who))[0] == 200


def test_an_agent_group_gets_one_version_first_and_a_group_name():
    versions: list[str] = []
    bus = bus_with("move", version=versions.append)
    a = bus.submit(Command("x.do", "agent", approval="user", group="quieter hats"))[1]
    b = bus.submit(Command("x.do", "agent", approval="user", group="quieter hats"))[1]
    c = bus.submit(Command("x.do", "agent", approval="user"))[1]
    assert versions == ["quieter hats", c["group"]]
    assert a["group"] == b["group"] == "quieter hats" and c["group"].startswith("agent-x.do-")


def test_your_own_moves_make_no_version():
    versions: list[str] = []
    bus_with("move", version=versions.append).submit(Command("x.do", "you", group="g"))
    assert versions == []


def test_the_wrong_set_guard_refuses_a_move_and_says_which_sets():
    guard = SetGuard("HW002_121_pp_finish", lambda: "HW002_121_pp_B")
    bus = bus_with("move", guard=guard)
    code, reply = bus.submit(Command("x.do", "you"))
    assert code == 409
    assert reply["error"] == "Live has HW002_121_pp_B open; this page is for HW002_121_pp_finish. Open that set first."
    assert bus_with("read", guard=guard).submit(Command("x.do", "you"))[0] == 200  # reading is not moving


def test_the_guard_passes_the_right_set_and_a_set_live_does_not_name():
    assert bus_with(guard=SetGuard("S", lambda: "S")).submit(Command("x.do"))[0] == 200
    assert bus_with(guard=SetGuard("S", lambda: "")).submit(Command("x.do"))[0] == 200


def test_the_guard_asks_live_once_per_ttl():
    now = [0.0]
    asked: list[int] = []
    guard = SetGuard("S", lambda: asked.append(1) or "S", ttl_s=5.0, clock=lambda: now[0])
    for t in (0.0, 1.0, 4.9, 5.0):
        now[0] = t
        guard.check()
    assert len(asked) == 2
    guard.forget()
    guard.check()
    assert len(asked) == 3


def test_a_bad_request_is_400_and_a_live_error_503():
    def bad(cmd):
        raise BadRequest("the body needs 'x'")

    def down(cmd):
        raise LiveError("Cannot reach Ableton")

    assert bus_with(handler=bad).submit(Command("x.do")) == (400, {"error": "the body needs 'x'"})
    assert bus_with(handler=down).submit(Command("x.do")) == (503, {"error": "Cannot reach Ableton"})


def test_a_refusal_carries_its_own_code():
    def refuse(cmd):
        raise Refused("not now", 423)

    assert bus_with(handler=refuse).submit(Command("x.do")) == (423, {"error": "not now"})


def test_a_command_that_cannot_get_live_in_time_is_refused_with_a_reason_not_dropped():
    class Busy:
        def execute(self, code):  # pragma: no cover - never called
            raise AssertionError

        def run(self, code):  # pragma: no cover
            raise AssertionError

    conn = LiveConnections(Busy())  # type: ignore[arg-type]
    held, release = threading.Event(), threading.Event()

    def hold():
        with conn.exclusive():
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        bus = bus_with(lock=lambda: conn.exclusive(wait_s=0.05))
        code, reply = bus.submit(Command("x.do"))
        assert code == 503 and "busy" in reply["error"]
        with pytest.raises(LiveBusy), conn.exclusive(wait_s=0.01):
            pass
    finally:
        release.set()
        t.join()
    assert bus.submit(Command("x.do"))[0] == 200  # free again


def test_the_guard_asks_live_with_no_lock_held_so_a_job_that_holds_live_can_forget():
    """A job holding Live (opening a set) calls forget(); a move asking Live must not hold the guard's lock meanwhile."""
    import threading

    asking, release = threading.Event(), threading.Event()

    def slow_open_set() -> str:
        asking.set()
        release.wait(5)
        return "S"

    guard = SetGuard("S", slow_open_set)
    asker = threading.Thread(target=guard.check)
    asker.start()
    assert asking.wait(5)
    forgetter = threading.Thread(target=guard.forget)
    forgetter.start()
    forgetter.join(2)
    stuck = forgetter.is_alive()
    release.set()
    asker.join(5)
    assert not stuck, "forget() waited for the guard's lock while Live was being asked"


def test_an_answer_asked_for_before_a_forget_is_not_kept_after_it():
    import threading

    started, release = threading.Event(), threading.Event()
    answers = iter(["OLD", "S"])

    def open_set() -> str:
        name = next(answers)
        started.set()
        if name == "OLD":
            release.wait(5)
        return name

    guard = SetGuard("S", open_set)
    t = threading.Thread(target=guard._name)
    t.start()
    assert started.wait(5)
    guard.forget()
    release.set()
    t.join(5)
    assert guard._name() == "S"


def test_the_bus_keeps_no_table_of_picked_options():
    assert not hasattr(bus_with("move"), "option_picked")


def test_a_handler_that_blows_up_is_a_500_that_answers_and_does_not_leak_the_arguments(capsys):
    def boom(cmd):
        raise KeyError("secret-token-in-args")

    bus = Bus()
    bus.register("x.boom", Spec(boom))
    code, reply = bus.submit(Command("x.boom", "you", {"token": "secret-token-in-args"}))
    assert code == 500 and "KeyError" in reply["error"] and "secret-token-in-args" not in reply["error"]
    assert bus.log[-1]["status"] == 500


def test_a_group_is_marked_versioned_only_after_its_version_was_saved():
    calls: list[str] = []

    def version(group):
        calls.append(group)
        if len(calls) == 1:
            raise LiveError("Live did not answer")

    bus = bus_with("move", version=version)
    assert bus.submit(Command("x.do", "agent", approval="user", group="g1"))[0] != 200  # the checkpoint failed
    assert bus.submit(Command("x.do", "agent", approval="user", group="g1"))[0] == 200
    assert bus.submit(Command("x.do", "agent", approval="user", group="g1"))[0] == 200
    assert calls == ["g1", "g1"]  # the second try saved it; the third found it saved


def test_the_versioned_groups_are_bounded(monkeypatch):
    monkeypatch.setattr("zpkt.app.bus.VERSIONED_KEEP", 3)
    bus = bus_with("move", version=lambda group: None)
    for n in range(6):
        bus.submit(Command("x.do", "agent", approval="user", group=f"g{n}"))
    assert list(bus._versioned) == ["g3", "g4", "g5"]
