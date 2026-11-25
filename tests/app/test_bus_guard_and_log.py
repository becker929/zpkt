"""Bus details that a mutation run showed no test pinned: the guard's TTL cache and its forget, the per-caller kinds,
the move's own set, and the length of the log."""

from __future__ import annotations

from zpkt.app.bus import KEEP_LOG, Bus, Command, SetGuard, Spec


def ok(cmd: Command):
    return 200, {}


def test_an_answer_is_kept_until_its_ttl_and_asked_again_after():
    now = [100.0]  # a late clock: a sum instead of a difference would never keep anything
    asked: list[int] = []
    guard = SetGuard("S", lambda: asked.append(1) or "S", ttl_s=5.0, clock=lambda: now[0])
    guard.check()
    now[0] = 102.0
    guard.check()
    assert len(asked) == 1
    now[0] = 105.5
    guard.check()
    assert len(asked) == 2


def test_forget_during_a_question_keeps_the_answer_out_of_the_cache():
    asked: list[int] = []
    holder: list[SetGuard] = []

    def open_set() -> str:
        asked.append(1)
        holder[0].forget()  # a set was opened while Live was being asked
        return "S"

    guard = SetGuard("S", open_set, clock=lambda: 100.0)
    holder.append(guard)
    guard.check()
    guard.check()
    assert len(asked) == 2  # the first answer was not kept


def test_forget_makes_the_next_check_ask_live_again():
    have = ["S"]
    guard = SetGuard("S", lambda: have[0], clock=lambda: 100.0)
    guard.check()
    have[0] = "Other"
    guard.check()  # still the kept answer
    guard.forget()
    try:
        guard.check()
    except Exception as exc:
        assert "Other" in str(exc)
    else:
        raise AssertionError("the guard did not ask Live again after forget")


def test_kinds_for_a_caller_lists_open_commands_and_its_own_only():
    bus = Bus()
    bus.register("a.open", Spec(ok))
    bus.register("b.api", Spec(ok, callers=("cli", "agent")))
    bus.register("c.you", Spec(ok, callers=("you",)))
    assert bus.kinds() == ["a.open", "b.api", "c.you"]
    assert bus.kinds("cli") == ["a.open", "b.api"]
    assert bus.kinds("you") == ["a.open", "c.you"]
    assert bus.kinds("booth") == ["a.open"]


def test_a_move_for_another_set_is_checked_against_that_set():
    spec = Spec(ok, "move", for_set="Mix")
    have = ["Mix"]
    bus = Bus(guard=SetGuard("Page", lambda: have[0]))
    bus.register("x.move", spec)
    assert bus.submit(Command("x.move"))[0] == 200  # Live has the move's set open, not the page's
    have[0] = "Page"
    bus2 = Bus(guard=SetGuard("Page", lambda: have[0]))
    bus2.register("x.move", spec)
    code, reply = bus2.submit(Command("x.move"))
    assert code == 409 and "Mix" in reply["error"]


def test_the_log_keeps_only_the_last_entries():
    bus = Bus()
    bus.register("x.do", Spec(ok))
    for _ in range(KEEP_LOG + 7):
        bus.submit(Command("x.do"))
    assert len(bus.log) == KEEP_LOG
