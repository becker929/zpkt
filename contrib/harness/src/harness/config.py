"""Where the harness keeps things, and how it reads its secrets.

Secrets come from the login Keychain (service names below, account = $USER),
never from files in the repo or from command lines.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ZPKT = Path(__file__).resolve().parents[4]     # contrib/harness/src/harness/config.py -> the repo


def agent_path(base: str | None = None) -> str:
    """PATH for agent sessions (Claude Code and Gemini CLI), with uv and ears' venv in front."""
    cur = base or os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    items = cur.split(":") if cur else []
    extra = [str(Path.home() / ".local" / "bin"), str(ZPKT / "ears" / ".venv" / "bin")]
    return ":".join([*(p for p in extra if p not in items), *items])

KEYCHAIN = {
    "oauth": "zpkt-claude-oauth",           # `claude setup-token` output -> CLAUDE_CODE_OAUTH_TOKEN
    "ntfy_topic": "zpkt-ntfy-topic",        # ntfy.sh topic for Gemini's questions
    "gemini": "zpkt-gemini-api-key",        # Gemini's image models, only through harness.images (contrib/docs/images.md)
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
    cli_path: str | None = os.environ.get("HARNESS_CLI")  # None: the SDK's bundled Claude Code
    extra_env: dict[str, str] = field(default_factory=dict)   # added to the environment of every Claude session
    # /skrng from the Mac (web.py): loopback port behind `tailscale serve`, and where it keeps
    # the password hash and the signed-in browsers.
    web_port: int = int(os.environ.get("HARNESS_WEB_PORT", "8787"))
    skrng_dir: Path = Path(os.environ.get("HARNESS_SKRNG", Path.home() / "_agent_scratch" / "skrng"))
    # The pages under /studio/: where they keep their data (the artist's, the regions', Gemini's), the working
    # directory of Gemini CLI sessions, the model the artist proposes with, and the small model of its quick question.
    studio_dir: Path = Path(os.environ.get("HARNESS_STUDIO", Path.home() / "_agent_scratch" / "studio"))
    studio_workdir: Path = Path(os.environ.get("HARNESS_STUDIO_WORKDIR", ZPKT))
    studio_model: str | None = os.environ.get("HARNESS_STUDIO_MODEL")
    narrator_model: str = os.environ.get("HARNESS_NARRATOR_MODEL", "claude-haiku-5-5")
    # The lab (/studio/lab/): HW002's stems and clips as the phone plays them, built by `harness lab-audio`.
    lab_audio: Path = Path(os.environ.get("HARNESS_LAB_AUDIO", Path.home() / "_agent_scratch" / "lab" / "audio"))
    # The site's published audio the checklist prototype plays (the gallery's renders), copied here on first use.
    site_audio: Path = Path(os.environ.get("HARNESS_SITE_AUDIO", Path.home() / "_agent_scratch" / "studio" / "site-audio"))
    # Every image made with Gemini, with its record (harness.images, contrib/docs/images.md); shown at /studio/images/.
    images_dir: Path = Path(os.environ.get("HARNESS_IMAGES", Path.home() / "_agent_scratch" / "studio" / "images"))
    # The regions' renders (contrib/docs/design/rummage.md): <regions_audio>/<region>/audio/<file>, made in Live, never in git.
    regions_audio: Path = Path(os.environ.get("HARNESS_REGIONS_AUDIO", Path.home() / "_agent_scratch" / "studio" / "regions"))

    @property
    def app_url(self) -> str:
        """This Mac's tailnet address (from `tailscale status`), for links in notifications."""
        try:
            out = subprocess.run(["tailscale", "status", "--self", "--json"], capture_output=True, text=True, timeout=5)
            name = json.loads(out.stdout)["Self"]["DNSName"].rstrip(".")
            return f"https://{name}"
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            return self.site


def claude_env(cfg: Config) -> dict[str, str]:
    """The environment every Claude Code session from the harness gets (the Keychain login, if there is one)."""
    env = dict(cfg.extra_env)
    env["PATH"] = agent_path(env.get("PATH"))
    token = secret("oauth")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env
