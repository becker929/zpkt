"""Kokoro through FluidAudio (Swift, Core ML on the Neural Engine): the same voice as voice.tts, its first audio in
~0.1 s rather than ~0.5 s (docs/voice-benchmark.md).

The helper (swift/, next to this file) is built on first use into VOICE_MODELS/fluid, in a directory that hashes its
sources, so no binary is committed and a changed source builds afresh. The build fetches FluidAudio 0.17.7 and the
text-normalisation library its manifest names (checked against the manifest's checksum), and applies
swift/fluidaudio-0.17.7.patch: masked fixed-length runs of the v3 source generator (exact lengths leak GPU memory,
GBs over a few hundred sentences), a local path for that library, and FLUIDAUDIO_CACHE, which keeps the models
under VOICE_MODELS too. The helper runs as a child of the worker; text goes over a piece at a time, so the first
audio is ready after the first sentence, and a stream that is dropped part way leaves nothing behind in the pipe.
Anything that keeps it from building or starting raises FluidUnavailable, with the reason.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import struct
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import numpy as np

from . import protocol
from .tts import models_dir, pieces

log = logging.getLogger("voice.fluid")

SWIFT = Path(__file__).with_name("swift")
VERSION = "0.17.7"
PATCH = SWIFT / f"fluidaudio-{VERSION}.patch"
SOURCE = f"https://github.com/FluidInference/FluidAudio/archive/refs/tags/v{VERSION}.tar.gz"
NEMO = "https://github.com/FluidInference/text-processing-rs/releases/download/v0.3.1/NemoTextProcessing.xcframework.zip"
NEMO_SHA256 = "5fa8c10d4ec26c1bb2413125f351a7222a4c68a23b74476680fbada7e26fc6aa"
PRODUCT = "kokoro-fluid"
READY_S = 900           # the first start downloads ~0.5 GB of models and compiles them
REPLY_S = 60            # a piece that takes longer than this means the helper is stuck
LEAD_MS, TAIL_MS = 40, 100      # silence kept around each piece: what the ONNX build leaves, give or take
_LEN = struct.Struct(">I")


class FluidUnavailable(RuntimeError):
    """The helper cannot be built or started here. The message says why."""


# --- building the helper -------------------------------------------------------------------------------------------
def sources() -> list[Path]:
    return [SWIFT / "Package.swift", PATCH, *sorted((SWIFT / "Sources").rglob("*.swift"))]


def build_dir(root: Path | None = None) -> Path:
    """Where the helper built from the current sources lives. Its name hashes them."""
    digest = hashlib.sha256(VERSION.encode())
    for path in sources():
        digest.update(path.read_bytes())
    return (root or models_dir() / "fluid") / f"build-{digest.hexdigest()[:12]}"


def find_swift() -> str | None:
    """swift, if the developer tools are installed. Without them /usr/bin/swift is a stub that puts an install
    dialog on the screen, so xcode-select is asked first."""
    swift = shutil.which("swift")
    if swift is None:
        return None
    try:
        tools = subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return swift if tools.returncode == 0 else None


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as reply:
        return reply.read()


def fetch_fluidaudio(into: Path) -> Path:
    """FluidAudio's source with the patch applied, in `into`/FluidAudio (the package name the manifest expects)."""
    src = into / "FluidAudio"
    if (src / ".patched").is_file():
        return src
    shutil.rmtree(src, ignore_errors=True)
    into.mkdir(parents=True, exist_ok=True)
    log.info("fetching FluidAudio %s", VERSION)
    with tarfile.open(fileobj=io.BytesIO(_download(SOURCE)), mode="r:gz") as tar:
        tar.extractall(into, filter="data")
    (into / f"FluidAudio-{VERSION}").rename(src)
    nemo = _download(NEMO)
    if hashlib.sha256(nemo).hexdigest() != NEMO_SHA256:
        raise FluidUnavailable("NemoTextProcessing.xcframework.zip does not match its checksum")
    with zipfile.ZipFile(io.BytesIO(nemo)) as z:
        z.extractall(src / "Vendor")
    done = subprocess.run(["patch", "-p1", "--forward", "--batch", "-i", str(PATCH)], cwd=src, capture_output=True,
                          text=True)
    if done.returncode != 0:
        raise FluidUnavailable(f"the FluidAudio patch does not apply: {(done.stdout + done.stderr).strip()[-400:]}")
    (src / ".patched").touch()
    return src


def build(root: Path | None = None, swift: str | None = None) -> Path:
    """The helper for the current sources: the one built before, else built now (a few minutes the first time)."""
    where = build_dir(root)
    binary = where / "release" / PRODUCT
    if binary.is_file():
        return binary
    swift = swift or find_swift()
    if swift is None:
        raise FluidUnavailable("no swift: the Xcode command line tools are not installed")
    try:
        src = fetch_fluidaudio(where)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise FluidUnavailable(f"cannot fetch FluidAudio: {exc}") from None
    log.info("building %s into %s", PRODUCT, where)
    t0 = time.monotonic()
    try:
        done = subprocess.run(
            [swift, "build", "-c", "release", "--disable-keychain", "--package-path", str(SWIFT),
             "--scratch-path", str(where), "--product", PRODUCT],
            capture_output=True, text=True, timeout=1800, env={**os.environ, "FLUIDAUDIO_SRC": str(src)})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FluidUnavailable(f"swift build: {exc}") from None
    if done.returncode != 0 or not binary.is_file():
        raise FluidUnavailable(f"swift build failed (exit {done.returncode}): "
                               f"{(done.stderr or done.stdout).strip()[-600:]}")
    log.info("built %s in %.0f s", PRODUCT, time.monotonic() - t0)
    for old in where.parent.glob("build-*"):        # helpers built from older sources
        if old != where:
            shutil.rmtree(old, ignore_errors=True)
    return binary


# --- the engine ----------------------------------------------------------------------------------------------------
def read_frame(stream: IO[bytes]) -> tuple[dict[str, Any], bytes] | None:
    """The next frame from the helper, or None at the end of its output."""
    def exactly(n: int) -> bytes | None:
        data = stream.read(n) if n else b""
        return data if len(data) == n else None

    if (head := exactly(4)) is None or (h := exactly(_LEN.unpack(head)[0])) is None:
        return None
    if (size := exactly(4)) is None or (payload := exactly(_LEN.unpack(size)[0])) is None:
        return None
    return json.loads(h), payload


def trim(pcm: np.ndarray, rate: int, lead_ms: int = LEAD_MS, tail_ms: int = TAIL_MS,
         floor_db: float = -60) -> np.ndarray:
    """The piece with its silences cut to `lead_ms` and `tail_ms`. This build pads every piece with ~0.3 s before
    and ~0.5 s after (the ONNX one with under 0.1 s), which would add 0.3 s to the wait for the first word."""
    hop = rate // 200                                   # 5 ms
    frames = pcm[: len(pcm) // hop * hop].astype(np.float32).reshape(-1, hop) / 32768
    loud = np.flatnonzero(np.sqrt((frames ** 2).mean(axis=1)) > 10 ** (floor_db / 20))
    if not len(loud):
        return pcm
    start = max(0, loud[0] * hop - lead_ms * rate // 1000)
    end = min(len(pcm), (loud[-1] + 1) * hop + tail_ms * rate // 1000)
    return pcm[start:end]


class KokoroFluid:
    name = "kokoro (fluid)"
    rate = 24_000

    def __init__(self, command: list[str] | None = None, models: Path | None = None):
        """`command` runs a helper that is already built (tests run a stand-in); by default it is built here."""
        self.models = models or models_dir()
        self.command = command or [str(build())]
        self.proc: subprocess.Popen | None = None
        self.ids = 0
        self.info = self._start()

    def _start(self) -> dict[str, Any]:
        env = {**os.environ, "FLUIDAUDIO_CACHE": str(self.models / "fluidaudio")}
        try:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        except OSError as exc:
            raise FluidUnavailable(f"cannot start the helper: {exc}") from None
        frame = self._reply(READY_S)
        if frame is None or frame[0].get("op") != "ready":
            self.close()
            raise FluidUnavailable(f"the helper did not start (exit {self.proc.poll()}); its log is on stderr")
        log.info("kokoro-fluid ready: %s", {k: v for k, v in frame[0].items() if k != "op"})
        return frame[0]

    def _reply(self, timeout: float) -> tuple[dict[str, Any], bytes] | None:
        """The helper's next frame. A helper that says nothing for `timeout` seconds is killed."""
        assert self.proc is not None and self.proc.stdout is not None
        watchdog = threading.Timer(timeout, self.proc.kill)
        watchdog.start()
        try:
            return read_frame(self.proc.stdout)
        finally:
            watchdog.cancel()

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def warmup(self) -> None:
        for _ in self.stream("Ready.", "af_heart", 1.0):
            pass

    def say(self, text: str, voice: str, speed: float) -> tuple[dict[str, Any], bytes]:
        """One piece, synthesised whole. A helper that died is started again first."""
        if self.proc is None or self.proc.poll() is not None:
            log.warning("kokoro-fluid exited (%s); starting it again", None if self.proc is None else self.proc.poll())
            self.info = self._start()
        assert self.proc is not None and self.proc.stdin is not None
        self.ids += 1
        rid = str(self.ids)
        try:
            self.proc.stdin.write(protocol.encode({"op": "say", "id": rid, "text": text, "voice": voice,
                                                   "speed": speed}))
            self.proc.stdin.flush()
        except OSError:
            pass                          # it died: the read below says so
        frame = self._reply(REPLY_S)
        if frame is None:
            self.close()
            raise RuntimeError("kokoro-fluid stopped mid-sentence")
        return frame

    def stream(self, text: str, voice: str, speed: float) -> Iterator[tuple[np.ndarray, int]]:
        speed = min(max(speed, 0.5), 2.0)
        for piece in pieces(text):
            header, payload = self.say(piece, voice, speed)
            if header["op"] == "error":    # nothing speakable in this piece (only symbols, say), or a failed run
                log.warning("skipped %r: %s", piece, header.get("msg"))
                continue
            if payload:
                rate = int(header["rate"])
                yield trim(np.frombuffer(payload, dtype="<i2").copy(), rate), rate
