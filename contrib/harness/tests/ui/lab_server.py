"""The harness's pages without the login, for the lab's browser tests and for trying the lab (/studio/lab/) by hand:
its files and audio, the artist agent's API (with a store of its own, and the rule-based quick question), and the
regions' state and renders.

    uv run --extra dev python tests/ui/lab_server.py [--port 8799] [--audio DIR]

serves http://127.0.0.1:8799/studio/lab/ the way the harness does (relative paths, so the page is the same file),
with the audio from HARNESS_LAB_AUDIO (built by `harness lab-audio`). The lab's browser tests use `app()`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web

from harness.config import Config
from harness.studio import Studio
from harness.studio.lab_audio import default_out


def app(audio: Path | None = None) -> web.Application:
    """The harness's own pages under /studio/, with every store in `audio` (default: the lab's audio folder), and
    the artist's quick question from its rules (no model)."""
    root_dir = Path(audio or default_out())
    cfg = Config(
        lab_audio=root_dir, studio_dir=root_dir, site_audio=root_dir / "site-audio", regions_audio=root_dir / "regions"
    )
    root = web.Application()
    root.add_subapp("/studio", Studio(cfg, question_model=False).app())
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--audio", type=Path)
    a = ap.parse_args()
    print(f"lab on http://127.0.0.1:{a.port}/studio/lab/")
    web.run_app(app(a.audio), host="127.0.0.1", port=a.port, print=None)
