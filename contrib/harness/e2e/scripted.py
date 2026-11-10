"""A stand-in for Claude, for the quick suites: the same work as Claude, without the model's minutes per turn.

It reads what the user said and does what Claude would through the same paths: a tool call the screens and the
narrator see, present_music with `ab`, and a short spoken reply. Its render is a small generated file (two bars,
A against B, a tone each), so the suites stay fast and need neither Live nor a kit. Anything it does not recognise
gets a one-line answer.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from harness.studio.agent import TextDelta, TextDone, ToolDone, ToolStart, TurnDone

RATE = 48_000
BAR_S = 1.5                    # one bar at 160 BPM
AB_HZ = {"A": 330.0, "B": 550.0}


async def narrate(prompt: str) -> str:
    """The narrator's model, scripted: a few words, every time."""
    return "Working on the rumble drive."


def ab_wav(path: Path, bars: int = 2) -> dict:
    """A stand-in A/B render: `bars` bars that alternate A's tone and B's, with a short fade at each bar's ends."""
    n = int(BAR_S * RATE)
    t = np.arange(n) / RATE
    fade = np.minimum(1.0, np.minimum(t, BAR_S - t) / 0.01)
    mono = np.concatenate([0.2 * fade * np.sin(2 * np.pi * AB_HZ["AB"[k % 2]] * t) for k in range(bars)])
    sf.write(str(path), np.stack([mono, mono], axis=1).astype(np.float32), RATE, subtype="PCM_16")
    return {"bar_seconds": BAR_S, "bars": bars, "first": "A", "every": 1}


class ScriptedClaude:
    def __init__(self) -> None:
        self.studio = None                 # set by the stack, once the Studio exists
        self.session_id = "scripted"
        self.prompts: list[str] = []
        self._n = 0

    async def turn(self, prompt: str):
        self.prompts.append(prompt)
        said = prompt.lower()
        if re.search(r"\ba ?b\b|against|versus", said):
            async for e in self._ab():
                yield e
        else:
            for e in self._say("Okay."):
                yield e
        yield TurnDone("", True, 0.0, self.session_id)

    async def interrupt(self) -> None:
        pass

    async def close(self) -> None:
        pass

    # --- what it does ------------------------------------------------------------------------------------------
    def _say(self, text: str):
        self._n += 1
        yield TextDelta(self._n, text)
        yield TextDone(self._n, text)

    async def _tool(self, command: str, work):
        """A Bash call as the SDK reports it, with the screens' hooks around it, running `work`."""
        self._n += 1
        tid = f"s{self._n}"
        args = {"command": command, "description": command.split(" --")[0][:60]}
        call = {"tool_name": "Bash", "tool_input": args}
        hooks = self.studio.screens.hooks()
        yield ToolStart(tid, "Bash", args)
        await hooks["pre"](call, tid, None)
        result = await work()
        await hooks["post"](call, tid, None)
        yield ToolDone(tid, "Bash", True, json.dumps(result)[:400])

    async def _ab(self):
        for e in self._say("Rendering forty against fifty."):
            yield e
        async def render():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "drive-40-vs-50.wav"
                ab = {**ab_wav(path), "labels": {"A": "drive 40%", "B": "drive 50%"}}
                await self.studio.conversation.present_music(path, "Drive forty versus fifty", ab,
                                                             "A is forty, B is fifty.")
            return {"rendered": 2}

        async for e in self._tool("render the rumble drive at 40% and 50%, A against B", render):
            yield e
        for e in self._say("Here it is."):
            yield e
