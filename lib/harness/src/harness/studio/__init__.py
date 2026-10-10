"""studio: the voice production app (docs/studio.md). `Studio` wires its parts together and runs them inside
`harness serve`: the web routes under /studio/, the voice worker, the Claude Code session, and a loopback-only
endpoint where scripts report their steps."""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Any

from aiohttp import web
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from ..config import Config
from ..jobs import JOB_TOOLS, job_env
from . import tools
from . import routes
from .agent import AgentSession
from .conversation import Conversation, Settings
from .hub import Hub
from .model import ShotLevel
from .narrator import Summarize, haiku
from .screens import Screens
from .shots import Capture
from .speech import VoiceWorker
from .store import Store

log = logging.getLogger(__name__)

VERSION = "1"

INSTRUCTIONS = """\
You are talking with Anthony through studio, a voice app on his phone (zpkt docs/studio.md). He hears what you \
write, read aloud by a speech model on the Mac, and sees it in a chat. He may be driving.

How to talk:
- Short, plain spoken sentences: usually one to three. No markdown, lists, tables, code, file paths or URLs unless \
he asks for them. Say numbers and units the way you would say them aloud.
- His words come from speech recognition: expect misheard words, read for meaning, and ask one short question when \
something is ambiguous. He ends each turn by saying "tomato"; the app removes it.
- Lines in [brackets] at the start of his message are notes from the app (for example, that he replayed a render).
- While you work, a small model narrates your tool calls to him, so don't announce each step. Do tell him what you \
found, decided or need.

What the app gives you, besides your usual tools:
- mcp__studio__present_music puts a render in the chat; it plays at once if he has autoplay on. Use it for anything \
he should hear. Fill in `ab` for a file that alternates two versions bar by bar.
- mcp__studio__play_music(loops) when he wants to hear it again or loop it a number of times.
- mcp__studio__stop_audio, and mcp__studio__screenshot (screenshots of your tool calls are already taken at the \
level he picked).
- The skills in .claude/skills are how music gets made here. Prefer them, and improve them (through a pull request) \
when you learn something.

Rules that still hold:
- Ableton Live: one checked step at a time. Before each step check that no dialog is open, the expected set is in \
front and Live answers; read the result back after it. Never chain unattended multi-step Live jobs, and never open \
or switch sets while the current one may be unsaved. If anything unexpected happens, stop and tell him.
- Sound changes are made in Live with its own devices, never with offline DSP.
- Saving means branch, push, pull request, merge. Never print secrets. Rig details (home paths, host names) never \
go into zpkt."""


class Studio:
    def __init__(self, cfg: Config, *, worker: VoiceWorker | None = None, agent: AgentSession | None = None,
                 capture: Capture | None = None, summarize: Summarize | None = None):
        self.cfg = cfg
        self.store = Store(cfg.studio_dir)
        self.hub = Hub()
        self.worker = worker or VoiceWorker(cfg.voice_command)
        self.screens = Screens(self.store, lambda: self.hub.shots_level, capture)
        self.steps_token = secrets.token_urlsafe(24)
        self.agent = agent or AgentSession(self._options)
        settings = Settings(stop_word=cfg.stop_word, voice=cfg.tts_voice, speed=cfg.tts_speed, version=VERSION)
        self.conversation = Conversation(store=self.store, hub=self.hub, agent=self.agent, worker=self.worker,
                                         summarize=summarize or haiku(cfg.narrator_model, cfg.cli_path, job_env(cfg)),
                                         screens=self.screens, settings=settings)
        self.screens.emit = self.conversation.add
        self._steps: web.AppRunner | None = None

    def _options(self, resume: str | None) -> ClaudeAgentOptions:
        hooks = self.screens.hooks()
        return ClaudeAgentOptions(
            cwd=str(self.cfg.studio_workdir),
            cli_path=self.cfg.cli_path,
            model=self.cfg.studio_model,
            allowed_tools=[*JOB_TOOLS, *tools.NAMES],
            permission_mode="acceptEdits",
            system_prompt={"type": "preset", "preset": "claude_code", "append": INSTRUCTIONS},
            setting_sources=["user", "project", "local"],
            include_partial_messages=True,
            mcp_servers={tools.SERVER: tools.server(self.conversation)},
            hooks={"PreToolUse": [HookMatcher(hooks=[hooks["pre"]])],
                   "PostToolUse": [HookMatcher(hooks=[hooks["post"]])],
                   "PostToolUseFailure": [HookMatcher(hooks=[hooks["post"]])]},
            env={**job_env(self.cfg), "STUDIO_STEP_URL": f"http://127.0.0.1:{self.cfg.steps_port}/step",
                 "STUDIO_STEP_TOKEN": self.steps_token},
            resume=resume,
        )

    def app(self) -> web.Application:
        sub = routes.app(self)
        sub.on_startup.append(self._on_startup)
        sub.on_cleanup.append(self._on_cleanup)
        return sub

    async def _on_startup(self, _app: web.Application) -> None:
        await self.start()

    async def _on_cleanup(self, _app: web.Application) -> None:
        await self.stop()

    async def start(self) -> None:
        await self.worker.start()
        self.conversation.start()
        await self._start_steps()

    async def stop(self) -> None:
        await self.conversation.stop()
        await self.worker.stop()
        if self._steps is not None:
            await self._steps.cleanup()
        self.store.close()

    # --- steps reported by scripts (loopback only; not forwarded by tailscale serve) ------------------------------
    async def _start_steps(self) -> None:
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_post("/step", self._step)
        self._steps = web.AppRunner(app, access_log=None)
        await self._steps.setup()
        try:
            await web.TCPSite(self._steps, "127.0.0.1", self.cfg.steps_port).start()
        except OSError as exc:
            log.warning("no step endpoint on port %d: %s", self.cfg.steps_port, exc)

    async def _step(self, request: web.Request) -> web.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(token, self.steps_token):
            return web.json_response({"error": "bad token"}, status=401)
        try:
            body: dict[str, Any] = await request.json()
            level = ShotLevel.parse(body.get("level", "minor"), ShotLevel.MINOR)
            caption = str(body.get("caption", "A step"))
            hint = (int(body["x"]), int(body["y"])) if "x" in body and "y" in body else None
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "expected {level, caption, x?, y?}"}, status=400)
        msg = await self.screens.shot(max(level, ShotLevel.MAJOR), caption, hint=hint)
        return web.json_response({"ok": True, "seq": msg.seq if msg else None})
