"""Gemini CLI in zpkt (contrib/docs/gemini.md). Two ways in, one agent:

    harness gemini [args]   Gemini CLI in a terminal, in this zpkt checkout, with the key from the Keychain (terminal.py)
    /studio/gemini/         the phone's view of Gemini CLI sessions (sessions.py), driven over ACP (acp.py), with
                            each turn's estimated cost (cost.py)

Gemini CLI does the work itself: it reads AGENTS.md (.gemini/settings.json), finds the skills in .agents/skills, and
edits files and runs commands with its own tools.
"""

from .acp import Acp, AcpError
from .cost import cost, image_cost, month_usage, price, turn_cost
from .sessions import MODES, Gemini, Session, phone_notify
from .terminal import exec_cli, gemini_command, keychain_key

__all__ = [
    "MODES",
    "Acp",
    "AcpError",
    "Gemini",
    "Session",
    "cost",
    "exec_cli",
    "gemini_command",
    "image_cost",
    "keychain_key",
    "month_usage",
    "phone_notify",
    "price",
    "turn_cost",
]
