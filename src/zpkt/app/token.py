"""The API's token files: one for each kind of caller, in ~/.config/zpkt/, readable only by you (mode 0600).

The API listens on localhost only and every call but /health must carry a token. Which token it is says who is
asking: the app stamps the call `cli`, `booth`, `demo` or `agent` by the token, never by what the caller says of
itself. The files are made when the app starts:

    app-token          the `zpkt` command (cli)
    app-token-booth    music-bot's booth
    app-token-demo     zpkt-demo
    app-token-agent    a coding agent in a terminal (ZPKT_AGENT=1)

There is no token for `you` or `minilab`: they are the web page and the hardware, never an API caller. A token is
never logged or printed. `ZPKT_CONFIG_DIR` names another folder (tests point it at a temp dir). Standard library
only: the client reads these too.

All four files belong to the same user, so this stops a caller claiming another's name by mistake or by a field in
the request. It does not stop a program that runs as you and chooses to read another caller's file.
"""

from __future__ import annotations

import contextlib
import hmac
import os
import secrets
import stat
from pathlib import Path

TOKEN_FILE = "app-token"
CLI = "cli"
CALLERS: tuple[str, ...] = ("agent", "booth", "demo", "cli")  # who may hold a token (zpkt.app.jobs.API_CALLERS)


def config_dir() -> Path:
    env = os.environ.get("ZPKT_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".config" / "zpkt"


def token_path(directory: Path | None = None, who: str = CLI) -> Path:
    """The token file of `who`. The cli's keeps the first name, app-token; the others add their name."""
    if who not in CALLERS:
        raise ValueError(f"there is no token for {who!r}; the API's callers are {', '.join(CALLERS)}")
    return (directory or config_dir()) / (TOKEN_FILE if who == CLI else f"{TOKEN_FILE}-{who}")


def ensure_token(directory: Path | None = None, who: str = CLI) -> str:
    """The token of `who`, made (mode 0600, in a folder only you can open) if there is none. An old file with looser
    permissions is tightened."""
    path = token_path(directory, who)
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


def ensure_tokens(directory: Path | None = None) -> dict[str, str]:
    """Every caller's token, made if missing: {who: token}."""
    return {who: ensure_token(directory, who) for who in CALLERS}


def who_holds(tokens: dict[str, str], sent: str) -> str | None:
    """Whose token `sent` is, or None. Every token is compared, each in constant time."""
    found = None
    for who, token in tokens.items():
        if hmac.compare_digest(sent.encode(), token.encode()):
            found = who
    return found


def read_token(directory: Path | None = None, who: str = CLI) -> str | None:
    """The token a client sends; None when the file is missing or empty (the app has not started)."""
    with contextlib.suppress(OSError):
        return token_path(directory, who).read_text().strip() or None
    return None
