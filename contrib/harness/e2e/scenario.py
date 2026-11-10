"""The scenario: what the virtual user does, in parts, and what each part expects of the app.

Claude is real, so what it says differs from run to run; the expectations are about what the app does with it (a
card of the right kind, an intro, the mic, the order of things), and the global rules are in checks.py.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from .checks import Result
from .phone import LISTENING, Phone


class Expect:
    def __init__(self) -> None:
        self.results: list[Result] = []

    def __call__(self, name: str, ok: bool, detail: Any = "", evidence: list[str] | None = None) -> bool:
        self.results.append(Result(name, bool(ok), str(detail)[:400], evidence or []))
        print(f"    {'PASS' if ok else 'FAIL'}  {name}: {str(detail)[:160]}", flush=True)
        return bool(ok)


# --- the parts ------------------------------------------------------------------------------------------------------

async def background(u: Phone, expect: Expect, ctx: dict) -> None:
    await u.wait(LISTENING, 120, "the page to listen")
    await u.switch_apps(6)
    since = await u.mark()
    heard = await u.say("Make an A B of the rumble drive on the long C kit, forty against fifty percent.")
    expect("After an app switch the mic hears the next line", "drive" in heard.lower(), heard)
    card = await u.wait_card("!!d.ab", since, 420, "an A/B card")
    ctx["ab"] = card
    await u.wait_turn_done(since, 420)


async def intents(u: Phone, expect: Expect, ctx: dict) -> None:
    since = await u.mark()
    await u.say("Loop that three times.")
    plays = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in'
        && e.msg.type === 'play').map((e) => e.msg)""")
    expect("'Loop that three times' plays the last render three times", any(p["loops"] == 3 for p in plays), plays)
    tools = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in' && e.msg.type === 'upsert'
        && e.msg.message.kind === 'activity').length""")
    expect("... without asking Claude", tools == 0, f"{tools} tool calls")
    await u.wait_turn_done(since, 300)


async def typed(u: Phone, expect: Expect, ctx: dict) -> None:
    since = await u.mark()
    await u.type("Thanks. In five words or fewer, what did I just hear?")
    await u.wait_turn_done(since, 300)
    replies = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in' && e.msg.type === 'speech'
        && e.msg.state === 'begin').length""")
    expect("A typed turn is answered out loud", replies > 0, f"{replies} speech streams")


async def long_wait(u: Phone, expect: Expect, ctx: dict) -> None:
    """The mic is offered and nobody speaks for longer than the recogniser's 45 s window (driving, thinking); the
    line that comes then is heard. A 6-minute quiet once cost the whole line."""
    quiet = ctx.get("quiet_s", 50)
    await u.wait(LISTENING, 120, "the page to listen")
    await u.note("quiet", seconds=quiet)
    await asyncio.sleep(quiet)
    since = await u.mark()
    heard = await u.say("What is the rumble drive set to now?")
    expect(f"After {quiet} s of quiet the line is heard", "drive" in heard.lower(), heard)
    await u.wait_turn_done(since, 300)


async def screens(u: Phone, expect: Expect, ctx: dict) -> None:
    shots = await u.js("""() => window.__wire.log.filter((e) => e.dir === 'in' && e.msg.type === 'upsert'
        && e.msg.message.kind === 'shots').length""")
    expect("Claude's steps come with screenshots", shots > 0, f"{shots} screenshot pairs")


PARTS: dict[str, Callable[[Phone, Expect, dict], Awaitable[None]]] = {
    "background": background, "intents": intents, "typed": typed, "long_wait": long_wait, "screens": screens,
}
NEEDS = {"intents": "background"}          # a replay needs a render in the chat

# Suites: which parts, whose Claude, and how long getUserMedia takes (an iPhone takes about 3 s).
SUITES = {
    "smoke": {"parts": ["background", "intents"], "scripted": True, "mic_delay_ms": 500, "quiet_s": 0,
              "about": "the core loop with a scripted Claude: an app switch, an A/B with its intro, a replay "
                       "(about 1 min)"},
    "quick": {"parts": list(PARTS), "scripted": True, "mic_delay_ms": 500, "quiet_s": 50,
              "about": "every part with a scripted Claude (about 3 min)"},
    "full": {"parts": list(PARTS), "scripted": False, "mic_delay_ms": 3000, "quiet_s": 90,
             "about": "every part with the real Claude and narrator, as Anthony uses it (about 10 min)"},
}


def plan(only: str | None, suite: str = "full") -> list[str]:
    if not only:
        return list(SUITES[suite]["parts"])
    want = [p.strip() for p in re.split(r"[,\s]+", only) if p.strip()]
    unknown = [p for p in want if p not in PARTS]
    if unknown:
        raise SystemExit(f"unknown parts {unknown}; the parts are {list(PARTS)}")
    for p in list(want):
        if p in NEEDS and NEEDS[p] not in want:
            want.insert(want.index(p), NEEDS[p])
    return want
