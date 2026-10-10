"""Where the harness keeps things, and how it reads its secrets.

Secrets come from the login Keychain (service names below, account = $USER),
never from files in the repo or from command lines.
"""

from __future__ import annotations

import getpass
import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ZPKT = Path(__file__).resolve().parents[4]     # lib/harness/src/harness/config.py -> the repo


def voice_command() -> list[str]:
    """How to start the voice worker: HARNESS_VOICE_CMD, else lib/voice through uv."""
    if os.environ.get("HARNESS_VOICE_CMD"):
        return shlex.split(os.environ["HARNESS_VOICE_CMD"])
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    return [uv, "run", "--project", str(ZPKT / "lib" / "voice"), "--extra", "engines", "voice", "serve"]

KEYCHAIN = {
    "rig_token": "zpkt-rig-token",          # Mac -> Worker socket (RIG_TOKEN on the Worker)
    "skrng_token": "skrng-token",           # read the owner's feedback from /api/skrng/feedback
    "oauth": "zpkt-claude-oauth",           # `claude setup-token` output -> CLAUDE_CODE_OAUTH_TOKEN
    "ntfy_topic": "zpkt-ntfy-topic",        # ntfy.sh topic for job start/finish
}


def keychain(service: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", getpass.getuser(), "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def secret(name: str) -> str | None:
    """Environment first (HARNESS_<NAME>), then the Keychain."""
    return os.environ.get(f"HARNESS_{name.upper()}") or keychain(KEYCHAIN[name])


@dataclass
class Config:
    site: str = os.environ.get("HARNESS_SITE", "https://anthonybecker.me")
    workdir: Path = Path(os.environ.get("HARNESS_WORKDIR", Path.home() / "Desktop"))
    jobs_dir: Path = Path(os.environ.get("HARNESS_JOBS", Path.home() / "_agent_scratch" / "jobs"))
    cli_path: str | None = os.environ.get("HARNESS_CLI")  # None: the SDK's bundled Claude Code
    model: str | None = os.environ.get("HARNESS_MODEL")
    job_turns: int = int(os.environ.get("HARNESS_JOB_TURNS", "400"))
    ask_turns: int = int(os.environ.get("HARNESS_ASK_TURNS", "12"))
    extra_env: dict[str, str] = field(default_factory=dict)
    # /skrng from the Mac (web.py): loopback port behind `tailscale serve`, and where it keeps
    # the password hash, sessions and feedback.
    web_port: int = int(os.environ.get("HARNESS_WEB_PORT", "8787"))
    skrng_dir: Path = Path(os.environ.get("HARNESS_SKRNG", Path.home() / "_agent_scratch" / "skrng"))
    # The old public route (browser -> anthonybecker.me /api/rpc -> socket -> Mac). Off: /skrng's
    # agent is reached over the tailnet only. HARNESS_PUBLIC_RPC=1 turns the socket back on.
    public_rpc: bool = os.environ.get("HARNESS_PUBLIC_RPC") == "1"
    # studio, the voice production app (docs/studio.md): where it keeps its chat and media, the Claude session's
    # working directory, the speech settings, and the loopback port scripts report steps to.
    studio_dir: Path = Path(os.environ.get("HARNESS_STUDIO", Path.home() / "_agent_scratch" / "studio"))
    studio_workdir: Path = Path(os.environ.get("HARNESS_STUDIO_WORKDIR", ZPKT))
    studio_model: str | None = os.environ.get("HARNESS_STUDIO_MODEL")
    narrator_model: str = os.environ.get("HARNESS_NARRATOR_MODEL", "claude-haiku-5-5")
    voice_command: list[str] = field(default_factory=voice_command)
    tts_voice: str = os.environ.get("HARNESS_TTS_VOICE", "af_heart")
    tts_speed: float = float(os.environ.get("HARNESS_TTS_SPEED", "1.0"))
    stop_word: str = os.environ.get("HARNESS_STOP_WORD", "tomato")
    steps_port: int = int(os.environ.get("HARNESS_STEPS_PORT", "8788"))

    @property
    def app_url(self) -> str:
        """This Mac's tailnet address (from `tailscale status`), for links in notifications."""
        try:
            out = subprocess.run(["tailscale", "status", "--self", "--json"], capture_output=True, text=True, timeout=5)
            name = json.loads(out.stdout)["Self"]["DNSName"].rstrip(".")
            return f"https://{name}"
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            return self.site

    @property
    def connect_url(self) -> str:
        return self.site.replace("https://", "wss://").replace("http://", "ws://") + "/api/rig/connect"
