"""A stand-in server for the lab (/studio/lab/) and the checklist (/studio/checklist/): their files, their audio, the
artist agent's API (with a store of its own, and the rule-based quick question) and the regions' state and renders,
no login, no studio.

    uv run --extra dev python tests/ui/lab_server.py [--port 8799] [--audio DIR]

serves http://127.0.0.1:8799/studio/lab/ the way the harness does (relative paths, so the page is the same file),
with the audio from HARNESS_LAB_AUDIO (built by `harness lab-audio`). The lab's browser tests use `app()`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web

from harness.studio import routes
from harness.studio.artist import SEED, Artist
from harness.studio.regions import RegionStore
from harness.studio.lab_audio import default_out


class _Cfg:
    def __init__(self, audio: Path):
        self.lab_audio = audio
        self.site = "https://anthonybecker.me"                       # the check sounds come from R2 through it
        self.check_sounds = Path(audio) / "check-sounds"
        self.site_audio = Path(audio) / "site-audio"
        self.images_dir = Path(audio) / "images"                    # the images' wall (harness.images)
        self.regions_audio = Path(audio) / "regions"                # <region>/audio/<file>: the regions' renders


class _Studio:
    def __init__(self, audio: Path):
        self.cfg = _Cfg(audio)
        self.artist = Artist(Path(audio) / "artist", SEED)
        self.artist_model = None                                     # the quick question comes from the rules
        self.regions = RegionStore(Path(audio) / "regions")          # the regions' state, beside their renders


def app(audio: Path | None = None) -> web.Application:
    sub = web.Application()
    sub[routes.STUDIO_KEY] = _Studio(audio or default_out())
    sub.router.add_get("/lab", routes.lab_slash)
    sub.router.add_get("/lab/audio/{name}", routes.lab_audio)
    sub.router.add_get("/lab/{path:.*}", routes.lab_file)
    sub.router.add_get("/checklist", routes.checklist_slash)
    sub.router.add_get("/checklist/map/sounds/{name}", routes.check_sound)
    sub.router.add_get("/checklist/{path:.*}", routes.checklist_file)
    sub.router.add_get("/site-audio/{path:.+}", routes.site_audio)
    routes.add_artist_routes(sub)
    routes.add_region_routes(sub)
    routes.add_image_routes(sub)
    root = web.Application()
    root.add_subapp("/studio", sub)
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--audio", type=Path)
    a = ap.parse_args()
    print(f"lab on http://127.0.0.1:{a.port}/studio/lab/")
    web.run_app(app(a.audio), host="127.0.0.1", port=a.port, print=None)
