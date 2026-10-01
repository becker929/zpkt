"""Audio metadata, read with ``ffprobe``.

Probing runs a subprocess per file, so it is the slow part of a scan. Only new
blobs are probed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT_S = 60


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What ffprobe reported about one file. Fields are None when unknown."""

    duration_s: float | None
    sample_rate: int | None
    channels: int | None
    codec: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def ffprobe_available() -> bool:
    """True when ffprobe is on PATH."""
    return shutil.which("ffprobe") is not None


def probe_file(path: Path, *, timeout_s: int = PROBE_TIMEOUT_S) -> ProbeResult:
    """Read duration, sample rate, channel count, and codec from a file.

    Never raises. A failure comes back as a :class:`ProbeResult` with ``error``
    set, so one unreadable file cannot stop a scan.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,codec_name:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd, capture_output=True, timeout=timeout_s, check=False
        )
    except FileNotFoundError:
        return _failed("ffprobe not found on PATH")
    except subprocess.TimeoutExpired:
        return _failed(f"ffprobe timed out after {timeout_s}s")

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        return _failed(detail or f"ffprobe exited {completed.returncode}")

    try:
        payload = json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        return _failed(f"unreadable ffprobe output: {exc}")

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    fmt = payload.get("format") or {}

    return ProbeResult(
        duration_s=_as_float(fmt.get("duration")),
        sample_rate=_as_int(stream.get("sample_rate")),
        channels=_as_int(stream.get("channels")),
        codec=stream.get("codec_name") or None,
    )


def _failed(message: str) -> ProbeResult:
    return ProbeResult(None, None, None, None, error=message)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)
