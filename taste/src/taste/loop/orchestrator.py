"""End-to-end taste loop orchestrator.

Drives the autonomous exploration cycle:
    hands record → ears analyze → taste judge → log verdict → repeat

Cross-repo calls go through CLI subprocesses, not Python imports.
This keeps the repo boundaries clean: no Python imports across repos.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path

from taste.models import Verdict
from taste.corpus.store import CorpusStore


class TasteOrchestrator:
    """Orchestrate the hands → ears → taste cycle.

    Args:
        hands_bin: path or name of the `hands` CLI.
        ears_bin: path or name of the `ears` CLI.
        store: CorpusStore for logging verdicts.
        judge: TasteModel for scoring (injected for testability).
    """

    def __init__(
        self,
        hands_bin: str = "hands",
        ears_bin: str = "ears",
        store: CorpusStore | None = None,
        judge: object | None = None,
    ) -> None:
        self._hands = hands_bin
        self._ears = ears_bin
        self._store = store or CorpusStore()
        self._judge = judge

    def run_cycle(self, config_path: str, *, beats: int = 64) -> Verdict:
        """Run one full production-and-evaluation cycle.

        Order:
          1. hands execute — build the project in Ableton from config
          2. hands record  — capture the output as audio
          3. ears analyze  — extract AudioProfile from the audio
          4. taste judge   — score the profile against the corpus
        """
        self._execute(config_path)
        render_path = self._record(config_path, beats)
        profile_json = self._analyze(render_path)
        verdict = self._do_judge(profile_json)
        return verdict

    def _execute(self, config_path: str) -> None:
        subprocess.run(
            [self._hands, "execute", "--config", config_path],
            check=True,
        )

    def _record(self, _config_path: str, beats: int) -> str:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            out = tmp.name
        subprocess.run(
            [self._hands, "record", "--beats", str(beats), "--output", out],
            check=True,
        )
        return out

    def _analyze(self, audio_path: str) -> str:
        result = subprocess.run(
            [self._ears, "analyze", audio_path, "--output", "-"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _do_judge(self, profile_json: str) -> Verdict:
        if self._judge is None:
            from taste.judge.taste_model import TasteModel
            self._judge = TasteModel()
        return self._judge.judge(profile_json)  # type: ignore[union-attr]
