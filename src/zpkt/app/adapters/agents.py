"""The Agents adapter: Ask, the chat with Claude and Gemini, and the tools they may use.

It makes the Ask service (zpkt.app.ask), puts the four agent commands on the bus (zpkt.app.agent_commands) and gives
the web server the /app/ask/ routes, as a mount (zpkt.app.mounts). Agents reach the app only through those four commands, tagged `agent` by the
bus. This module changes nothing in Live and imports nothing from zpkt.live.

Data lives in ZPKT_ASK_DIR (default ~/_agent_scratch/zpkt-app/ask), in Zpkt web's file forms: point it at a copy of
Zpkt web's data folder to carry its sessions over. Keys come only from the harness's secret lookup.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from zpkt.app import agent_commands
from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.ask.claude import ClaudeProvider
from zpkt.app.ask.gemini import GeminiProvider
from zpkt.app.ask.provider import Provider
from zpkt.app.ask.routes import PREFIX, AskRoutes
from zpkt.app.ask.service import Ask
from zpkt.app.ask.tools import ToolGate
from zpkt.app.proposals import OptionStore

GUIDE = Path(__file__).resolve().parents[1] / "static" / "ask" / "agent-guide.md"

Secret = Callable[[str], str | None]


def ask_dir() -> Path:
    env = os.environ.get("ZPKT_ASK_DIR")
    return Path(env).expanduser() if env else Path.home() / "_agent_scratch" / "zpkt-app" / "ask"


def default_secret() -> Secret:
    """The existing secret lookup (the harness's: HARNESS_<NAME>, then the Keychain). None found: no keys."""
    try:
        from harness.config import secret
    except ImportError:
        return lambda name: None
    return secret


class AgentsAdapter:
    name = "agents"

    def __init__(
        self,
        context: AppContext,
        data_dir: Path | None = None,
        secret: Secret | None = None,
        providers: dict[str, Provider] | None = None,
        home: Path | None = None,
    ) -> None:
        self.context = context
        self.data_dir = data_dir or ask_dir()
        self.secret = secret or default_secret()
        self.providers = providers
        self.home = home
        self.ask: Ask | None = None
        self.routes: AskRoutes | None = None

    def start(self) -> None:
        bus = self.context.bus
        options = OptionStore(self.data_dir)
        agent_commands.register(bus, self.context.desk, options)
        providers = self.providers or self.default_providers()
        guide = GUIDE.read_text() if GUIDE.exists() else ""
        self.ask = Ask(self.data_dir, providers, ToolGate(bus), guide, home=self.home)
        self.routes = AskRoutes(self.ask, self.home)
        self.context.desk.mounts.add(PREFIX, self.routes)

    def default_providers(self) -> dict[str, Provider]:
        return {
            "claude": ClaudeProvider(self.secret),
            "gemini": GeminiProvider(self.secret, usage_file=self.data_dir / "usage.jsonl"),
        }

    def stop(self) -> None:
        if self.routes is not None:
            self.context.desk.mounts.remove(PREFIX)
        for p in self.ask.providers.values() if self.ask else ():
            close = getattr(p, "close", None)
            if close is not None:
                close()


def make(context: AppContext) -> AgentsAdapter:
    return AgentsAdapter(context)


ADAPTER = AdapterSpec("agents", make)
