"""The booth's settings (BOOTH_HOME/config.toml, all optional) and its one secret, the bot's token.

The token comes from BOOTH_TOKEN, else the login Keychain (service zpkt-booth-token, account = $USER), as the
harness reads its secrets. `booth token --new` makes one.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime

from . import HOME

KEYCHAIN_SERVICE = "zpkt-booth-token"


@dataclass
class Settings:
    port: int = 8794                     # clear of the harness (8787/8788), studio dev (8790/8791), Room World (8970)
    hours: list[str] = field(default_factory=lambda: ["10:00-23:00"])   # local time; the booth starts jobs only inside
    queue_max: int = 10
    keep_days: int = 30
    quiet_s: float = 300.0               # no job starts while something else used the LOM this recently
    video_size: tuple[int, int] = (1080, 1920)
    palette: str = ""                    # the palette GET /v1/guide serves; "" is palette.SERVED

    def in_hours(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        minute = now.hour * 60 + now.minute
        for span in self.hours:
            a, b = span.split("-")
            lo = int(a[:2]) * 60 + int(a[3:])
            hi = int(b[:2]) * 60 + int(b[3:])
            if (lo <= minute < hi) if lo <= hi else (minute >= lo or minute < hi):
                return True
        return False


def settings() -> Settings:
    path = HOME / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.is_file() else {}
    s = Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__})
    s.video_size = tuple(s.video_size)
    return s


def token() -> str | None:
    if os.environ.get("BOOTH_TOKEN"):
        return os.environ["BOOTH_TOKEN"]
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", getpass.getuser(), "-w"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value.startswith("zb1_") else None
