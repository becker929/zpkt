"""The real studio for a run: the server in this process on a loopback port, the voice worker (Kokoro, Parakeet),
the real Claude session and narrator, with its data in the run's folder.

Plans see Live's renders already in the cache (each entry linked, so a run never changes them) and render anything
new as stand-in tones at the kit's tempo, so a run never touches Live, unless it is --live. Screenshots come from a
stand-in screen that changes at every capture, unless it is --real-screen.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from aiohttp.test_utils import TestServer

from harness.config import Config, voice_command
from harness.studio import Studio
from harness.studio.shots import Frame
from harness.studio.speech import VoiceWorker
from harness.web import App

PLANS = Path(os.environ.get("HANDS_PLANS", "~/_agent_scratch/plans")).expanduser()

# The real Claude, told what a test run is: without it, it rightly stops before presenting stand-in tones as music.
TEST_NOTE = ("This session is an automated end-to-end test of the app, not Anthony. The user is a virtual tester. "
             "Plans already in the cache play Live's renders; anything new renders as stand-in tones on purpose "
             "(HANDS_PLAN_RENDERER=fake), because tests never touch Live. Treat stand-ins as renders: bake, present "
             "and play them as usual, and you may say in a few words that they are stand-ins. Do not stop to ask.")


class MovingScreen:
    """A screen where something moves at every capture, so the saliency, the zoom and every shot level have work."""

    def __init__(self) -> None:
        self.n = 0

    async def grab(self) -> Frame:
        self.n += 1
        px = np.full((1080, 1920, 3), 24, np.uint8)
        x = 80 + (self.n * 37) % 1500
        px[300:520, x:x + 260] = (200, 120, 60)
        return Frame(px, asyncio.get_running_loop().time())


@dataclass
class Stack:
    server: TestServer
    studio: Studio
    cfg: Config
    base: str
    env: dict[str, str]

    async def close(self) -> None:
        await self.server.close()


def seed_plans(dst: Path) -> int:
    """Link every render in the real cache into the run's cache. New renders land in the run's folder only."""
    entries = dst / "entries"
    entries.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in sorted((PLANS / "entries").glob("*")):
        if (src / "plan.json").is_file() and (src / "audio.wav").is_file():
            (entries / src.name).symlink_to(src, target_is_directory=True)
            n += 1
    return n


async def start(run: Path, *, live: bool = False, real_screen: bool = False, scripted: bool = False) -> Stack:
    """The studio for a run. `scripted` puts the stand-in for Claude and the narrator's model (scripted.py) in place
    of the real ones, for the quick suites."""
    env: dict[str, str] = {}
    if not live:
        env["HANDS_PLANS"] = str(run / "plans")
        env["HANDS_PLAN_RENDERER"] = "fake"
        seed_plans(run / "plans")
    os.environ.update(env)                 # the Claude session and its Bash commands inherit them
    cfg = Config(jobs_dir=run / "jobs", skrng_dir=run / "skrng", studio_dir=run / "studio", steps_port=0,
                 extra_env=env, studio_note=TEST_NOTE if not live else "")
    agent = None
    if scripted:
        from .scripted import ScriptedClaude, narrate
        agent = ScriptedClaude()
    studio = Studio(cfg, worker=VoiceWorker(voice_command()), capture=None if real_screen else MovingScreen(),
                    agent=agent, summarize=narrate if scripted else None)
    if agent is not None:
        agent.studio = studio
    server = TestServer(App(cfg, None, cfg.skrng_dir, secure_cookie=False, studio=studio).build(), host="127.0.0.1")
    await server.start_server()
    if not await studio.worker.wait_ready(300):
        await server.close()
        raise RuntimeError("the voice worker (Kokoro, Parakeet) did not start in 5 minutes")
    return Stack(server, studio, cfg, str(server.make_url("")).rstrip("/"), env)
