"""Narration: only after a quiet spell, not too often, never stale, never about nothing new."""

import asyncio

from harness.studio.narrator import Narrator, clean


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


async def test_narration_waits_for_quiet_and_new_activity():
    clock, spoken, prompts = Clock(), [], []

    async def summarize(prompt):
        prompts.append(prompt)
        return '"I\'m rendering the louder kick now."'

    n = Narrator(summarize, spoken.append, clock)
    n.turn_started("make the kick louder")
    n.turn_ended()                                      # stop the background watcher; drive ticks by hand
    n._turn = 7
    n.note("Run render_plan")
    assert await n.tick(7) is None                      # Claude was just heard (the turn started)
    clock.t += n.QUIET_S
    assert await n.tick(7) == "I'm rendering the louder kick now."
    assert spoken == ["I'm rendering the louder kick now."] and "Run render_plan" in prompts[0]
    clock.t += n.QUIET_S
    assert await n.tick(7) is None                      # nothing new happened
    n.note("Read the result")
    assert await n.tick(7) is None                      # too soon after the last line
    clock.t += n.MIN_GAP_S
    assert await n.tick(7) is not None and "Read the result" in prompts[1] and "Run render_plan" not in prompts[1]


async def test_a_line_that_went_stale_is_dropped():
    clock, spoken = Clock(), []
    n = Narrator(None, spoken.append, clock)

    async def slow(prompt):
        clock.t += 1
        n.spoke()                                       # Claude spoke while the line was being written
        return "I'm checking the levels."

    n._summarize = slow
    n.turn_started("x")
    n.turn_ended()
    n._turn = 3
    n.note("Measure loudness")
    clock.t += n.QUIET_S
    assert await n.tick(3) is None and spoken == []


async def test_a_failing_model_says_nothing():
    clock = Clock()

    async def broken(prompt):
        raise RuntimeError("no login")

    n = Narrator(broken, lambda line: None, clock)
    n.turn_started("x")
    n.turn_ended()
    n._turn = 1
    n.note("a")
    clock.t += n.QUIET_S
    assert await n.tick(1) is None


def test_lines_are_cleaned_and_capped():
    assert clean('  "Rendering\n now."  ', 16) == "Rendering now."
    assert clean(" ".join(["word"] * 30), 5) == "word word word word word."
