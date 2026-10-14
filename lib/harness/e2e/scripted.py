"""A stand-in for Claude, for the quick suites: the same work as Claude, without the model's minutes per turn.

It reads what the user said and does what Claude would through the same paths: `hands plan` on the command line
(cached Live renders, stand-ins for new ones), present_music with the printed `options` or `ab`, a tool call the
screens and the narrator see, and a short spoken reply. Its renders are small so the suites stay fast: 4 stops on
the long C kit, one bar each, and 2-bar A/Bs. Anything it does not recognise gets a one-line answer.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

from harness.config import ZPKT
from harness.studio import tools
from harness.studio.agent import TextDelta, TextDone, ToolDone, ToolStart, TurnDone

UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
KIT = "c8x16"
DRIVE = "rumble|plugin:Decapitator|Drive"


async def narrate(prompt: str) -> str:
    """The narrator's model, scripted: a few words, every time."""
    return "Working on the rumble drive."


async def hands(*args: str) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(UV, "run", "--project", str(ZPKT / "hands"), "--extra", "plans",
                                                "hands", "plan", *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"hands plan {args[0]} failed: {err.decode()[-600:]}")
    return json.loads(out)


def percent(label: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", label)
    return float(m.group()) / 100 if m else 0.0


class ScriptedClaude:
    def __init__(self) -> None:
        self.studio = None                 # set by the stack, once the Studio exists
        self.session_id = "scripted"
        self.prompts: list[str] = []
        self._n = 0

    async def turn(self, prompt: str):
        self.prompts.append(prompt)
        said = prompt.lower()
        if "finer" in said and "between" in said:
            m = re.search(r"between ([\d.]+%) and ([\d.]+%)", prompt)
            lo, hi = (percent(m.group(1)), percent(m.group(2))) if m else (0.4, 0.6)
            async for e in self._slider(lo, hi, "Finer rumble drive", "A closer look at that range."):
                yield e
        elif "slider" in said:
            async for e in self._slider(0.0, 1.0, "Rumble drive", "Four steps from clean to crushed."):
                yield e
        elif re.search(r"\ba ?b\b|against|versus", said):
            async for e in self._ab():
                yield e
        elif said.lstrip("[ ").startswith("keep") or " keep " in said:
            for e in self._say("Kept. That is the new starting point."):
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

    async def _present(self, made: dict[str, Any], title: str, note: str, kind: str) -> None:
        conv = self.studio.conversation
        if kind == "options":
            await conv.present_music(Path(made["path"]), title, None, note, options=tools.baked_options(made["options"]))
        else:
            x = made["ab"]
            ab = {"bar_seconds": x["bar_seconds"], "bars": x["bars"], "first": x["first"], "every": x["every"],
                  "labels": {"A": x["a"], "B": x["b"]}}
            await conv.present_music(Path(made["path"]), title, ab, note)

    async def _slider(self, lo: float, hi: float, title: str, note: str):
        for e in self._say("Baking a slider for the rumble drive."):
            yield e
        made: dict[str, Any] = {}

        async def bake():
            made.update(await hands("slider", KIT, DRIVE, "--from", f"{lo:.4f}", "--to", f"{hi:.4f}", "--stops", "4",
                                    "--bars", "1"))
            return {"rendered": made["rendered"], "cached": made["cached"]}

        async for e in self._tool(f"hands plan slider {KIT} '{DRIVE}' --from {lo:.2f} --to {hi:.2f} --stops 4", bake):
            yield e
        await self._present(made, title, note, "options")
        for e in self._say("It's on your phone."):
            yield e

    async def _ab(self):
        for e in self._say("Rendering forty against fifty."):
            yield e
        made: dict[str, Any] = {}
        a = json.dumps({"kit": KIT, "knobs": {DRIVE: 0.4}, "label": "drive 40%"})
        b = json.dumps({"kit": KIT, "knobs": {DRIVE: 0.5}, "label": "drive 50%"})

        async def render():
            made.update(await hands("ab", a, b, "--bars", "2", "--no-write-ahead"))
            return {"rendered": made["rendered"]}

        async for e in self._tool("hands plan ab A B --bars 2", render):
            yield e
        await self._present(made, "Drive forty versus fifty", "A is forty, B is fifty.", "ab")
        for e in self._say("Here it is."):
            yield e

