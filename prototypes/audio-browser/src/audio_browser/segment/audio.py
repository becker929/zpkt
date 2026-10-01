"""Decoding audio for the classifiers.

Every classifier wants the same thing: mono 32-bit float samples at one rate,
in blocks small enough to hold in memory. ffmpeg does the decoding, exactly as
:mod:`audio_browser.peaks` does, so every format the collection holds works
without a second audio library.

Nothing is written to disk. The longest sound in the collection is close to
twelve hours, which is about 2.7 GB as 16 kHz float samples, so blocks are
streamed and dropped rather than held. A caller that needs the whole signal at
once must ask for it, and only short files should.

Files are opened read-only. ``compost/`` holds the only copies of these
recordings and is mounted read-only on purpose.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    from numpy.typing import NDArray

    FloatArray = NDArray[np.float32]
else:  # pragma: no cover - runtime alias
    FloatArray = object

DECODE_TIMEOUT_S = 1800
_READ_BYTES = 1 << 20  # 1 MB of PCM per read


class DecodeError(Exception):
    """Raised when ffmpeg could not produce samples for a file."""


def load_untyped(factory: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a model factory that carries no usable type information.

    ``transformers`` ships partial annotations: some ``from_pretrained``
    classmethods are typed, some are not, and the typed ones do not describe
    ``.to(device)`` giving back the same class. Routing the call through this
    helper keeps ``mypy --strict`` meaningful where the annotations are real —
    at this package's own function signatures — instead of scattering
    suppressions through the classifiers.
    """
    return factory(*args, **kwargs)


def ffmpeg_available() -> bool:
    """True when ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def decode_blocks(
    path: Path,
    *,
    sample_rate: int,
    block_samples: int,
    overlap_samples: int = 0,
    timeout_s: int = DECODE_TIMEOUT_S,
) -> Iterator[tuple[int, "FloatArray"]]:
    """Yield ``(start_sample, samples)`` blocks of mono float audio.

    Consecutive blocks overlap by ``overlap_samples``, so a classifier with a
    window wider than its hop can keep an unbroken frame grid across a block
    boundary. The final block may be shorter than ``block_samples``; a block
    holding nothing but overlap from the previous one is not yielded.

    ``start_sample`` counts from the start of the file, including the overlap,
    so ``start_sample / sample_rate`` is the block's position in seconds.
    """
    import numpy as np

    if block_samples <= 0:
        raise ValueError("block_samples must be positive")
    if not 0 <= overlap_samples < block_samples:
        raise ValueError("overlap_samples must be at least 0 and less than a block")

    advance = block_samples - overlap_samples
    proc = _spawn(path, sample_rate)
    stderr_chunks: list[bytes] = []

    def drain() -> None:
        assert proc.stderr is not None
        stderr_chunks.append(proc.stderr.read())

    # ffmpeg blocks once its stderr pipe fills, so drain it on its own thread.
    drainer = threading.Thread(target=drain, daemon=True)
    drainer.start()

    assert proc.stdout is not None
    held = np.zeros(0, dtype=np.float32)
    emitted = 0  # samples of `held` that started an already-yielded block
    leftover = b""
    try:
        while True:
            raw = proc.stdout.read(_READ_BYTES)
            if not raw:
                break
            if leftover:
                raw = leftover + raw
                leftover = b""
            extra = len(raw) % 4
            if extra:
                leftover = raw[-extra:]
                raw = raw[:-extra]
            if not raw:
                continue
            held = np.concatenate(
                (held, np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=False))
            )
            while len(held) >= block_samples:
                yield emitted, held[:block_samples].copy()
                held = held[advance:]
                emitted += advance
        if len(held) > overlap_samples or (emitted == 0 and len(held) > 0):
            yield emitted, held.copy()
        proc.stdout.close()
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise DecodeError(f"ffmpeg timed out after {timeout_s}s") from exc
    finally:
        if proc.poll() is None:  # the consumer stopped early
            proc.kill()
            proc.wait()
        drainer.join(timeout=5)

    if returncode != 0:
        detail = b"".join(stderr_chunks).decode("utf-8", "replace").strip()
        raise DecodeError(detail or f"ffmpeg exited {returncode}")


def decode_all(
    path: Path, *, sample_rate: int, timeout_s: int = DECODE_TIMEOUT_S
) -> "FloatArray":
    """Decode a whole file into one array. Only sane for short sounds."""
    import numpy as np

    parts = [
        block
        for _, block in decode_blocks(
            path,
            sample_rate=sample_rate,
            block_samples=sample_rate * 60,
            timeout_s=timeout_s,
        )
    ]
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts).astype(np.float32, copy=False)


def _spawn(path: Path, sample_rate: int) -> subprocess.Popen[bytes]:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-",
    ]
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise DecodeError("ffmpeg not found on PATH") from exc
