"""Shared fixtures. Every test runs offline against generated WAV files.

No test reads the real audio collection.
"""

from __future__ import annotations

import math
import shutil
import sqlite3
import struct
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from audio_browser.config import Config, ProjectsConfig, Root
from audio_browser.db import open_db
from audio_browser.scan import scan_roots
from audio_browser.server.app import create_app


def write_wav(
    path: Path,
    *,
    seconds: float = 0.1,
    freq: float = 440.0,
    sample_rate: int = 8000,
    amplitude: float = 0.5,
    channels: int = 1,
) -> Path:
    """Write a small sine-wave WAV file. Deterministic for the same arguments."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sample_rate)
    peak = int(amplitude * 32767)
    data = bytearray()
    for i in range(frames):
        value = int(peak * math.sin(2 * math.pi * freq * i / sample_rate))
        data += struct.pack("<h", value) * channels
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(channels)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(bytes(data))
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "index.db"


@pytest.fixture
def conn(db_path: Path):
    connection = open_db(db_path)
    yield connection
    connection.close()


@pytest.fixture
def two_roots(tmp_path: Path) -> tuple[Root, Root]:
    """A source tree and a byte-for-byte copy of it, mirroring the real case."""
    source = tmp_path / "source"
    copy = tmp_path / "copy"
    write_wav(source / "kicks" / "kick.wav", freq=60)
    write_wav(source / "kicks" / "kick-again.wav", freq=60)  # same bytes
    write_wav(source / "hats" / "hat.wav", freq=1000)
    (source / "notes.txt").write_text("not audio")
    (source / "project.rpp").write_text("not audio either")
    shutil.copytree(source, copy)
    return (
        Root(name="source", path=source.resolve()),
        Root(name="copy", path=copy.resolve()),
    )


@pytest.fixture
def config_two_roots(db_path: Path, two_roots: tuple[Root, Root]) -> Config:
    return Config(db_path=db_path, roots=two_roots)


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def have_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg not on PATH")
needs_ffprobe = pytest.mark.skipif(not have_ffprobe(), reason="ffprobe not on PATH")


@dataclass(frozen=True)
class Fixture:
    """A running API over a small generated collection."""

    client: TestClient
    db_path: Path
    tmp_path: Path
    hashes: dict[str, str]  # filename -> hash

    def hash_of(self, filename: str) -> str:
        return self.hashes[filename]

    @property
    def projects_dir(self) -> Path:
        """Where this fixture's project files live. One per test, in tmp_path."""
        return self.tmp_path / "projects"

    def make_project(self, name: str, **body: object) -> dict[str, object]:
        """Create a project and return its summary, failing loudly if refused."""
        response = self.client.post("/api/projects", json={"name": name, **body})
        assert response.status_code == 201, response.text
        return cast(dict[str, object], response.json())

    def project_id(self, name: str, **body: object) -> str:
        return cast(str, self.make_project(name, **body)["id"])


def schemas_dir() -> Path:
    """The generated JSON Schema directory, beside ``src`` and ``frontend``.

    The tests validate against the same file the server does. There is no second
    copy of the schema for the suite to agree with while production disagrees.
    """
    return Path(__file__).resolve().parents[1] / "schemas"


def _quiet(_: str) -> None:
    return None


@pytest.fixture
def capped_api(tmp_path: Path) -> Iterator[Callable[[int], Fixture]]:
    """The same API, built with a cap of the caller's choosing.

    The cap is meant to be turned down, so the suite has to be able to turn it
    down. A board with one slot per column is where every refusal actually
    fires, and building it needs no fixture of its own.
    """
    clients: list[TestClient] = []

    def build(cap: int) -> Fixture:
        fixture = _build_api(
            tmp_path,
            ProjectsConfig(
                dir=tmp_path / "projects",
                schemas_dir=schemas_dir(),
                stored_cap=cap,
                collage_cap=cap,
                enrich_cap=cap,
            ),
        )
        clients.append(fixture.client)
        fixture.client.__enter__()
        return fixture

    try:
        yield build
    finally:
        for client in clients:
            client.__exit__(None, None, None)


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Fixture]:
    """Two roots holding the same three files, so every blob has two aliases."""
    fixture = _build_api(tmp_path, None)
    with fixture.client:
        yield fixture


def _build_api(tmp_path: Path, projects: ProjectsConfig | None) -> Fixture:
    """Index three generated sounds and wrap the API round them."""
    source = tmp_path / "source"
    write_wav(source / "kick.wav", freq=60, seconds=0.5)
    write_wav(source / "hat.wav", freq=1000, seconds=0.2)
    # WAV bytes under an .mp3 name. The index and the API key on the extension,
    # so this exercises extension filtering and Content-Type mapping without
    # needing an encoder.
    write_wav(source / "loop.mp3", freq=220, seconds=0.4)
    copy = tmp_path / "copy"
    if not copy.exists():
        shutil.copytree(source, copy)

    db_path = tmp_path / "index.db"
    conn = open_db(db_path)
    scan_roots(
        conn,
        [Root("source", source.resolve()), Root("copy", copy.resolve())],
        workers=2,
        probe=False,
        log=_quiet,
    )
    # ffprobe is optional in this suite, so durations are set by hand. They only
    # need to be distinct and ordered for the sort and filter tests.
    durations = {"kick.wav": 1.5, "hat.wav": 0.25, "loop.mp3": 30.0}
    hashes: dict[str, str] = {}
    for name, seconds in durations.items():
        row = conn.execute(
            "SELECT hash FROM alias WHERE filename = ? LIMIT 1", (name,)
        ).fetchone()
        hashes[name] = row["hash"]
        conn.execute(
            "UPDATE blob SET duration_s = ?, codec = 'pcm_s16le', sample_rate = 8000,"
            " channels = 1, probed_at = '2026-01-01T00:00:00+00:00' WHERE hash = ?",
            (seconds, row["hash"]),
        )
    conn.commit()
    conn.close()

    app = create_app(db_path, projects=projects)
    return Fixture(
        client=TestClient(app), db_path=db_path, tmp_path=tmp_path, hashes=hashes
    )


def peek(db_path: Path, sql: str, *params: object) -> sqlite3.Row:
    """Read one row straight from the index, around the API."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(sql, params).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def tree_snapshot(root: Path) -> dict[str, int]:
    """Every file under a directory and its size.

    Comparing one of these before and after a request is how the suite proves a
    route left the filesystem alone. It catches a removal, a truncation and a
    rewrite alike, which an existence check would not.
    """
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
