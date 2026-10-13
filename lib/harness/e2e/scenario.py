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


def card_sel(seq: int) -> str:
    return f'#messages [data-seq="{seq}"]'


async def options_of(u: Phone, seq: int) -> dict[str, Any]:
    return await u.js(f"""() => {{
      const el = document.querySelector('{card_sel(seq)}');
      return {{ pick: Number(el.dataset.pick), shown: el.querySelector('.opt-value').textContent,
               labels: [...el.querySelectorAll('.opt-tick, .opt-button')].length }};
    }}""")


def number(label: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", label)
    return float(m.group()) if m else float("nan")


# --- the parts ------------------------------------------------------------------------------------------------------

async def slider(u: Phone, expect: Expect, ctx: dict) -> None:
    since = await u.mark()
    heard = await u.say("Give me a slider for the rumble drive on the long C kit, the whole range, sixteen stops.")
    expect("The request is understood", "slider" in heard.lower() and "drive" in heard.lower(), heard)
    card = await u.wait_card("d.options && d.options.layout === 'slider'", since, 420, "a slider card")
    ctx["slider"] = card
    opts = card["data"]["options"]
    # While the Mac sweeps it, the card shows (and Keep and Finer mean) the option that sounds.
    await u.wait(f"() => window.studio.engine.position()?.seq === {card['seq']}", 300, "the sweep to start")
    await u.shot("sweep")
    agree = []
    for _ in range(4):
        pos = await u.js("window.studio.engine.position()")
        seen = await options_of(u, card["seq"])
        if pos and pos.get("option") is not None:
            agree.append((pos["option"], seen["pick"]))
        await asyncio.sleep(opts["bar_seconds"] * 1.3)
    expect("During the sweep the card shows the option that sounds", agree and all(a == b for a, b in agree), agree)
    await u.wait_turn_done(420)
    await u.drain()                                   # the engine's log, up to now
    swept = [e for e in u.recording.engine if e.get("seq") == card["seq"] and e.get("counted")
             and e.get("kind") == "music"]           # the intro is speech for the same card
    n, bar = len(opts["options"]), opts["bar_seconds"]
    expect("The Mac's play sweeps a bar of each option",
           swept and abs((swept[0]["stopAt"] - swept[0]["t0"]) - n * bar) < 0.05,
           f"{n} options x {bar} s; played {[(round(e['stopAt'] - e['t0'], 2), e['outcome']) for e in swept]}")


async def finer(u: Phone, expect: Expect, ctx: dict) -> None:
    card = ctx["slider"]
    labels = [o["label"] for o in card["data"]["options"]["options"]]
    k = len(labels) - 3
    await u.tap_option(card["seq"], k)                  # touching the slider plays that option, held
    await u.wait(f"() => window.studio.engine.position()?.option === {k}", 10, "the option to play")
    await asyncio.sleep(3)
    seen = await options_of(u, card["seq"])
    expect("A tap on the slider holds that option", seen["pick"] == k and seen["shown"] == labels[k], seen)
    since = await u.mark()
    await u.tap(f"{card_sel(card['seq'])} [data-action='opt-finer']", "Finer here")
    text = await u.wait_user_message(since, 30)
    expect("Finer here names the neighbours of the option on screen",
           labels[k - 1] in text and labels[k + 1] in text and labels[k] in text, text)
    new = await u.wait_card("!!d.options", since, 420, "a finer slider")
    got = [o["label"] for o in new["data"]["options"]["options"]]
    near = lambda a, b: abs(number(a) - number(b)) <= 1.0          # labels gain decimals as the steps shrink
    expect("The finer slider spans those neighbours", got and near(got[0], labels[k - 1]) and near(got[-1], labels[k + 1]),
           f"{got[0] if got else '?'} to {got[-1] if got else '?'} (wanted {labels[k - 1]} to {labels[k + 1]})")
    ctx["finer"] = new
    await u.wait_turn_done(420)


async def background(u: Phone, expect: Expect, ctx: dict) -> None:
    await u.wait(LISTENING, 120, "the page to listen")
    await u.switch_apps(6)
    since = await u.mark()
    heard = await u.say("Make an A B of the rumble drive on the long C kit, forty against fifty percent.")
    expect("After an app switch the mic hears the next line", "drive" in heard.lower(), heard)
    card = await u.wait_card("!!d.ab", since, 420, "an A/B card")
    ctx["ab"] = card
    await u.wait_turn_done(420)


async def intents(u: Phone, expect: Expect, ctx: dict) -> None:
    since = await u.mark()
    await u.say("Loop that three times.")
    plays = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in'
        && e.msg.type === 'play').map((e) => e.msg)""")
    expect("'Loop that three times' plays the last render three times", any(p["loops"] == 3 for p in plays), plays)
    tools = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in' && e.msg.type === 'upsert'
        && e.msg.message.kind === 'activity').length""")
    expect("... without asking Claude", tools == 0, f"{tools} tool calls")
    await u.wait_turn_done(300)


async def keep(u: Phone, expect: Expect, ctx: dict) -> None:
    card = ctx.get("finer") or ctx["slider"]
    labels = [o["label"] for o in card["data"]["options"]["options"]]
    k = len(labels) // 2
    await u.tap_option(card["seq"], k)
    await asyncio.sleep(2.5)
    since = await u.mark()
    await u.tap(f"{card_sel(card['seq'])} .opt-act--keep", "Keep")
    text = await u.wait_user_message(since, 30)
    expect("Keep names the option on screen", labels[k] in text, text)
    await u.wait_turn_done(300)


async def typed(u: Phone, expect: Expect, ctx: dict) -> None:
    since = await u.mark()
    await u.type("Thanks. In five words or fewer, what did I keep?")
    await u.wait_turn_done(300)
    replies = await u.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in' && e.msg.type === 'speech'
        && e.msg.state === 'begin').length""")
    expect("A typed turn is answered out loud", replies > 0, f"{replies} speech streams")


async def screens(u: Phone, expect: Expect, ctx: dict) -> None:
    shots = await u.js("""() => window.__wire.log.filter((e) => e.dir === 'in' && e.msg.type === 'upsert'
        && e.msg.message.kind === 'shots').length""")
    expect("Claude's steps come with screenshots", shots > 0, f"{shots} screenshot pairs")


PARTS: dict[str, Callable[[Phone, Expect, dict], Awaitable[None]]] = {
    "slider": slider, "finer": finer, "background": background, "intents": intents, "keep": keep, "typed": typed,
    "screens": screens,
}
NEEDS = {"finer": "slider", "keep": "slider"}

# Suites: which parts, whose Claude, and how long getUserMedia takes (an iPhone takes about 3 s).
SUITES = {
    "smoke": {"parts": ["slider", "background", "intents"], "scripted": True, "mic_delay_ms": 500,
              "about": "the core loop with a scripted Claude: a slider with its intro and sweep, an app switch, a "
                       "replay (about 1 min)"},
    "quick": {"parts": list(PARTS), "scripted": True, "mic_delay_ms": 500,
              "about": "every part with a scripted Claude (about 3 min)"},
    "full": {"parts": list(PARTS), "scripted": False, "mic_delay_ms": 3000,
             "about": "every part with the real Claude and narrator, as Anthony uses it (about 15 min)"},
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
