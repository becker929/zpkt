"""Where the harness keeps things, and how it reads its secrets.

Secrets come from the login Keychain (service names below, account = $USER),
never from files in the repo or from command lines.
"""

from __future__ import annotations

import getpass
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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

    @property
    def connect_url(self) -> str:
        return self.site.replace("https://", "wss://").replace("http://", "ws://") + "/api/rig/connect"
