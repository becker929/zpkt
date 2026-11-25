"""The API's token file: ~/.config/zpkt/app-token, made when the app starts, readable only by you (mode 0600).

The API listens on localhost only and every call but /health must carry the token. The token is never logged or
printed. `ZPKT_CONFIG_DIR` names another folder (tests point it at a temp dir). Standard library only: the client
reads it too.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from pathlib import Path

TOKEN_FILE = "app-token"


def config_dir() -> Path:
    env = os.environ.get("ZPKT_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".config" / "zpkt"


def token_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / TOKEN_FILE


def ensure_token(directory: Path | None = None) -> str:
    """The token, made (mode 0600, in a folder only you can open) if there is none. An old file with looser
    permissions is tightened."""
    path = token_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            path.chmod(0o600)
        token = path.read_text().strip()
        if token:
            return token
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


def read_token(directory: Path | None = None) -> str | None:
    """The token a client sends; None when the file is missing or empty (the app has not started)."""
    with contextlib.suppress(OSError):
        return token_path(directory).read_text().strip() or None
    return None
