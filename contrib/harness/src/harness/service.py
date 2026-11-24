"""`harness serve`: the web server (web.py) with the pages under /studio/, on loopback until stopped.

Claude Code jobs, their RPC and the public socket to the site were removed on 24 November 2026 (Anthony: "what
we're doing right now replaces that"); git tag `pre-upgrade-2026-11-24` has them.
"""

from __future__ import annotations

from .config import Config


async def serve(cfg: Config) -> None:
    from .studio import Studio
    from .web import run

    await run(cfg, Studio(cfg))
