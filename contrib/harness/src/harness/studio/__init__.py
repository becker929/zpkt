"""The pages under /studio/, behind the harness password: a home page, the HW002 lab, Gemini CLI sessions, the
artist agent's API, and the regions' state and renders. `Studio` holds their stores and builds the sub-app.

The spoken chat that once lived here was removed on 24 November 2026 (git tag `pre-upgrade-2026-11-24` has it)."""

from __future__ import annotations

from aiohttp import web

from ..config import Config, claude_env
from . import routes
from .artist import SEED, Artist, QuestionLines
from .regions import RegionStore


class Studio:
    def __init__(self, cfg: Config, *, question_model: bool = True):
        self.cfg = cfg
        # The artist agent's store and its quick question's model (contrib/docs/design/artist-agent.md)
        self.artist = Artist(cfg.studio_dir / "artist", SEED)
        self.artist_model = (
            QuestionLines(cfg.artist_question_model, cfg.cli_path, claude_env(cfg)) if question_model else None
        )
        # The regions' permanent state (contrib/docs/design/rummage.md)
        self.regions = RegionStore(cfg.studio_dir / "regions")

    def app(self) -> web.Application:
        sub = routes.app(self)
        sub.on_cleanup.append(self._on_cleanup)
        return sub

    async def _on_cleanup(self, _app: web.Application) -> None:
        await self.close()

    async def close(self) -> None:
        if self.artist_model is not None:
            await self.artist_model.close()
        self.artist.close()
