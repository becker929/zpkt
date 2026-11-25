"""Writes hands' contracts in lib/contracts. The logic lives in zpkt.live.schemas; this path stays for the old command.

uv run python hands/tools/gen_schemas.py
"""

from zpkt.live.schemas import *  # noqa: F403
from zpkt.live.schemas import write_all

if __name__ == "__main__":
    write_all()
