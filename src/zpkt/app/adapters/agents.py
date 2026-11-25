"""The Agents adapter: Ask, the chat with Claude and Gemini, and the tools they may use.

It makes the Ask service (zpkt.app.ask), puts the four agent commands on the bus (zpkt.app.agent_commands) and gives
the web server the /app/ask/ routes, as a mount (zpkt.app.mounts). Agents reach the app only through those four commands, tagged `agent` by the
bus. This module changes nothing in Live and imports nothing from zpkt.live.

Data lives in ZPKT_ASK_DIR (default ~/_agent_scratch/zpkt-app/ask), in Zpkt web's file forms: point it at a copy of
Zpkt web's data folder to carry its sessions over. Keys come only from the harness's secret lookup.
"""

from __future__ import annotations

import getpass
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.app import agent_commands
from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.ask.claude import ClaudeProvider
from zpkt.app.ask.gemini import GeminiProvider
from zpkt.app.ask.provider import Provider
from zpkt.app.ask.routes import PREFIX, AskRoutes
from zpkt.app.ask.service import Ask
from zpkt.app.ask.tools import ToolGate

GUIDE = Path(__file__).resolve().parents[1] / "static" / "ask" / "agent-guide.md"

Secret = Callable[[str], str | None]


def ask_dir() -> Path:
    env = os.environ.get("ZPKT_ASK_DIR")
    return Path(env).expanduser() if env else Path.home() / "_agent_scratch" / "zpkt-app" / "ask"


# The harness's Keychain items (contrib/harness/src/harness/config.py KEYCHAIN), for when the harness is not
# installed in the app's environment (it is not in the root .venv).
KEYCHAIN = {"oauth": "zpkt-claude-oauth", "gemini": "zpkt-gemini-api-key"}


def keychain_secret(name: str, run: Callable[..., Any] = subprocess.run) -> str | None:
    """HARNESS_<NAME> from the environment, then the Keychain item for `name`; None when neither has it."""
    if value := os.environ.get(f"HARNESS_{name.upper()}"):
        return value
    service = KEYCHAIN.get(name)
    if not service:
        return None
    try:
        out = run(
            ["security", "find-generic-password", "-s", service, "-a", getpass.getuser(), "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def default_secret() -> Secret:
    """The existing secret lookup (the harness's: HARNESS_<NAME>, then the Keychain), or the same lookup here when
    the harness is not installed."""
    try:
        from harness.config import secret
    except ImportError:
        return keychain_secret
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
        self.context.desk.options.keep_proposals_in(self.data_dir)  # options.json stays in Ask's folder
        agent_commands.register(bus, self.context.desk)
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
