"""`harness gemini`: Gemini CLI in a terminal, in this zpkt checkout, with the key from the Keychain in its environment
only. Also where the harness finds the gemini command and the key for the phone's sessions."""

from __future__ import annotations

import os
import shutil


def gemini_command() -> list[str]:
    if os.environ.get("HARNESS_GEMINI_CMD"):
        return os.environ["HARNESS_GEMINI_CMD"].split()
    return [shutil.which("gemini") or "/opt/homebrew/bin/gemini"]


def exec_cli(args: list[str]) -> None:
    """`harness gemini`: Gemini CLI in the zpkt checkout, the key in its environment only."""
    from ..config import ZPKT, agent_path, secret

    key = secret("gemini")
    if not key:
        raise SystemExit("No Gemini key: add it to the Keychain as zpkt-gemini-api-key (account $USER).")
    cmd = gemini_command()
    os.chdir(ZPKT)
    os.execvpe(
        cmd[0],
        [*cmd, *(args[1:] if args[:1] == ["--"] else args)],
        {**os.environ, "PATH": agent_path(), "GEMINI_API_KEY": key, "GEMINI_CLI_TRUST_WORKSPACE": "true"},
    )


def keychain_key() -> str | None:
    """The Gemini key: HARNESS_GEMINI, else the Keychain's zpkt-gemini-api-key."""
    from ..config import secret

    return secret("gemini")
