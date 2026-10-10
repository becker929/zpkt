"""Capturing the screen: through the screengrab helper (ScreenCaptureKit), else through `screencapture`.

The helper's source (screengrab.swift, next to this file) is compiled on first use into the studio's data directory,
under a name that hashes the source, so no binary is committed and a changed source builds afresh. One helper
process stays running: a capture costs ~40 ms rather than the ~130 ms of a spawned `screencapture`, and while a
tool runs at firehose level it holds a stream open, whose latest frame takes a few ms to read, and nothing at all
to compare while the screen is still. Without swiftc, or once the helper keeps failing, captures go through
`screencapture`, whose PNGs are converted to sRGB.

Screen Recording belongs to the process that started the harness, and tmux holds it. A process without it captures
only the wallpaper, so when the helper reports that it lacks it, screenshots turn off (CaptureUnavailable) instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from PIL import Image, ImageCms

from .shots import Frame, Rect

log = logging.getLogger(__name__)

SOURCE = Path(__file__).with_name("screengrab.swift")
SWIFTC_FLAGS = ("-O", "-swift-version", "6", "-parse-as-library",
                "-framework", "ScreenCaptureKit", "-framework", "CoreMedia", "-framework", "CoreVideo")
NO_PERMISSION = ("Screenshots are off: the harness has no Screen Recording permission. Start it from tmux, which "
                 "holds that permission, to have them back.")


class CaptureError(RuntimeError):
    """This capture failed; the next one may work."""


class CaptureUnavailable(CaptureError):
    """No capture can work in this process. The message says why, for the chat."""


class HelperError(CaptureError):
    """The helper failed, didn't answer, or is gone."""


class BuildError(RuntimeError):
    """The helper could not be compiled."""


class Capture(Protocol):
    """The screen, as screens.py uses it."""

    async def grab(self) -> Frame: ...


@runtime_checkable
class Streaming(Capture, Protocol):
    """A capture that can hold a stream open while tools run, so a firehose look reads the latest frame (the same
    Frame again while nothing changed) instead of taking one. It holds a process: it is closed when the app stops."""

    async def watch(self, fps: int) -> None: ...

    async def latest(self) -> Frame: ...

    async def unwatch(self) -> None: ...

    async def close(self) -> None: ...


# --- building the helper -------------------------------------------------------------------------------------------
def helper_path(bin_dir: Path, source: Path = SOURCE) -> Path:
    """Where the helper built from `source` lives. Its name hashes the source and the flags it is built with."""
    digest = hashlib.sha256(source.read_bytes() + "\0".join(SWIFTC_FLAGS).encode()).hexdigest()
    return bin_dir / f"screengrab-{digest[:12]}"


def find_swiftc() -> str | None:
    """swiftc, if the developer tools are installed. Without them /usr/bin/swiftc is a stub that puts an install
    dialog on the screen, so xcode-select is asked first."""
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        return None
    try:
        tools = subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return swiftc if tools.returncode == 0 else None


def build(bin_dir: Path, source: Path = SOURCE, swiftc: str | None = None) -> Path:
    """The helper for `source`: the one built before, else compiled now (a few seconds). Raises BuildError."""
    path = helper_path(bin_dir, source)
    if path.is_file():
        return path
    swiftc = swiftc or find_swiftc()
    if swiftc is None:
        raise BuildError("no swiftc: the Xcode command line tools are not installed")
    bin_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    t0 = time.monotonic()
    try:
        try:
            done = subprocess.run([swiftc, *SWIFTC_FLAGS, "-o", str(tmp), str(source)], capture_output=True,
                                  text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BuildError(f"swiftc: {exc}") from None
        if done.returncode != 0 or not tmp.is_file():
            raise BuildError(f"swiftc failed: {(done.stderr or done.stdout).strip()[-600:]}")
        tmp.replace(path)                  # in one step, so nobody ever starts a half-written helper
    finally:
        tmp.unlink(missing_ok=True)
    log.info("built %s in %.1f s", path.name, time.monotonic() - t0)
    return path


# --- the helper process --------------------------------------------------------------------------------------------
def load_bgra(path: Path, w: int, h: int, bpr: int) -> np.ndarray:
    """A frame the helper wrote (rows of `bpr` bytes, BGRA, maybe padded) as H x W x 3 RGB, read-only."""
    rows = np.fromfile(path, np.uint8, count=bpr * h).reshape(h, bpr)
    pixels = np.ascontiguousarray(rows[:, : w * 4].reshape(h, w, 4)[:, :, 2::-1])
    pixels.flags.writeable = False
    return pixels


class Helper:
    """The screengrab process: one command per line in, one JSON object per line out (see screengrab.swift).

    Calls go one at a time, and it is started on the first. A call that times out, or is cancelled half way, leaves
    the process out of step with its replies, so the process is killed and the next call starts a fresh one."""

    def __init__(self, command: list[str], frame_file: Path, timeout: float = 10.0):
        self.command, self.frame_file, self.timeout = command, frame_file, timeout
        self.preflight: bool | None = None          # has Screen Recording: known once the process has started
        self.streaming = False
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._latest: tuple[int, Frame] | None = None   # the stream frame read last, with its number

    async def call(self, line: str) -> dict[str, Any]:
        """Send one command and return its reply. Raises HelperError."""
        async with self._lock:
            return await self._call(line)

    async def shot(self) -> Frame:
        """A capture of the main display."""
        async with self._lock:
            reply = await self._call(f"shot {self.frame_file}", capture=True)
            return Frame(await self._load(reply), time.monotonic())

    async def start(self, fps: int) -> None:
        """Open a stream at up to `fps` frames a second; frame() reads its latest."""
        async with self._lock:
            await self._call(f"start {int(fps)}", capture=True)
            self.streaming, self._latest = True, None

    async def frame(self) -> Frame:
        """The stream's latest frame; the same Frame again while the screen hasn't changed."""
        async with self._lock:
            reply = await self._call(f"frame {self.frame_file}")
            if self._latest is None or self._latest[0] != reply["seq"]:
                self._latest = (reply["seq"], Frame(await self._load(reply), time.monotonic()))
            return self._latest[1]

    async def stop(self) -> None:
        """Close the stream."""
        async with self._lock:
            self.streaming, self._latest = False, None
            if self._proc is not None and self._proc.returncode is None:     # no process, no stream
                await self._call("stop")

    async def front(self) -> Rect | None:
        """The front window's bounds in screen pixels (a modal alert or an open menu counts), if one is on screen."""
        bounds = (await self.call("front")).get("bounds")
        return tuple(bounds) if bounds else None

    async def close(self) -> None:
        """End the process (closing its stdin ends it; one that hangs is killed). The next call starts a new one."""
        proc, self._proc = self._proc, None
        self.streaming, self._latest = False, None
        if proc is None or proc.returncode is not None:
            return
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def _call(self, line: str, capture: bool = False) -> dict[str, Any]:
        proc = await self._running()
        if capture and not self.preflight:
            raise CaptureUnavailable(NO_PERMISSION)
        name = line.split()[0]
        try:
            proc.stdin.write(line.encode() + b"\n")
            await proc.stdin.drain()
            reply = await asyncio.wait_for(self._reply(proc), self.timeout)
        except BaseException as exc:
            self._kill()                    # out of step with its replies, or gone: a fresh one next time
            if isinstance(exc, TimeoutError):
                raise HelperError(f"{name}: no answer in {self.timeout:g} s") from None
            if isinstance(exc, OSError):
                raise HelperError(f"{name}: {exc}") from None
            raise
        if not reply.get("ok"):
            raise HelperError(f"{name}: {reply.get('error', 'failed')}")
        return reply

    async def _running(self) -> asyncio.subprocess.Process:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        self.streaming, self._latest = False, None
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            raise HelperError(f"cannot start screengrab: {exc}") from None
        try:
            ready = await asyncio.wait_for(self._reply(self._proc), self.timeout)
        except BaseException as exc:
            self._kill()
            if isinstance(exc, TimeoutError):
                raise HelperError(f"screengrab not ready in {self.timeout:g} s") from None
            raise
        if not ready.get("ready") or not ready.get("ok"):
            self._kill()
            raise HelperError(f"screengrab not ready: {ready.get('error', ready)}")
        self.preflight = bool(ready.get("preflight"))
        return self._proc

    async def _reply(self, proc: asyncio.subprocess.Process) -> dict[str, Any]:
        """The next reply, past any notice (noting the one that matters: the stream stopped)."""
        while line := await proc.stdout.readline():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "event" not in msg:
                return msg
            if msg["event"] == "stream_stopped":
                self.streaming, self._latest = False, None
                log.warning("screengrab's stream stopped: %s", msg.get("error"))
        raise HelperError("screengrab exited")

    async def _load(self, reply: dict[str, Any]) -> np.ndarray:
        try:
            return await asyncio.to_thread(load_bgra, self.frame_file, reply["w"], reply["h"], reply["bpr"])
        except (OSError, ValueError, KeyError) as exc:
            raise HelperError(f"unreadable frame: {exc}") from None

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self.streaming, self._latest = False, None
        if proc is not None and proc.returncode is None:
            proc.kill()


# --- the fallback --------------------------------------------------------------------------------------------------
def load_srgb(path: Path) -> np.ndarray:
    """An image file as RGB in sRGB, read-only. screencapture's PNGs carry the display's own colour profile; the
    phone shows sRGB, so the colours are converted."""
    with Image.open(path) as im:
        icc = im.info.get("icc_profile")
        rgb = im.convert("RGB")
    if icc:
        rgb = ImageCms.profileToProfile(rgb, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                        ImageCms.createProfile("sRGB"), outputMode="RGB")
    pixels = np.asarray(rgb)
    pixels.flags.writeable = False
    return pixels


async def screencapture(timeout: float = 15.0) -> Frame:
    """The main display through macOS's `screencapture` (~130 ms, and ~50 ms more to convert its colours)."""
    fd, name = tempfile.mkstemp(suffix=".png", prefix="studio-shot-")
    os.close(fd)
    path = Path(name)
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-D", "1", "-t", "png", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise CaptureError(f"no screencapture: {exc}") from None
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            raise CaptureError("screencapture hung") from None
        if proc.returncode != 0 or path.stat().st_size == 0:
            raise CaptureError(f"screencapture failed: {err.decode(errors='replace').strip()[:200]}")
        t = time.monotonic()
        return Frame(await asyncio.to_thread(load_srgb, path), t)
    finally:
        path.unlink(missing_ok=True)


# --- the capture the app uses --------------------------------------------------------------------------------------
class ScreenGrab:
    """The main display: through the helper when it builds and runs, else through `screencapture`."""

    MAX_FAILURES = 3            # helper failures in a row before screencapture takes over for good

    def __init__(self, bin_dir: Path, *, source: Path = SOURCE, swiftc: str | None = None, timeout: float = 10.0):
        self.bin_dir, self.source, self.swiftc, self.timeout = bin_dir, source, swiftc, timeout
        self.helper: Helper | None = None
        self._scratch: Path | None = None       # where the helper writes frames: private to this user
        self._fallback = False
        self._failures = 0
        self._lock = asyncio.Lock()

    async def grab(self) -> Frame:
        """A capture now, with the front window's bounds when the helper is there to find them."""
        helper = await self._helper()
        if helper is not None:
            try:
                frame = await helper.shot()
                frame.window = await helper.front()
            except HelperError as exc:
                await self._failed(exc)
            else:
                self._failures = 0
                return frame
        return await screencapture()

    async def watch(self, fps: int) -> None:
        """Hold a stream open for latest() to read. Without one, latest() captures (and says what is wrong)."""
        helper = await self._helper()
        if helper is not None:
            try:
                await helper.start(fps)
            except HelperError as exc:
                await self._failed(exc)
            except CaptureUnavailable:
                pass

    async def latest(self) -> Frame:
        """The stream's latest frame (the same Frame while nothing changed), or a capture when there is no stream."""
        helper = self.helper
        if helper is not None and helper.streaming:
            try:
                return await helper.frame()
            except HelperError as exc:
                await self._failed(exc)
        return await self.grab()

    async def unwatch(self) -> None:
        helper = self.helper
        if helper is not None and helper.streaming:
            try:
                await helper.stop()
            except HelperError as exc:
                await self._failed(exc)

    async def close(self) -> None:
        if self.helper is not None:
            await self.helper.close()
        if self._scratch is not None:
            shutil.rmtree(self._scratch, ignore_errors=True)

    async def _helper(self) -> Helper | None:
        """The helper, built (or found built) on first use; None once screencapture has taken over."""
        async with self._lock:
            if self.helper is None and not self._fallback:
                try:
                    path = await asyncio.to_thread(build, self.bin_dir, self.source, self.swiftc)
                except BuildError as exc:
                    log.warning("screenshots through screencapture: %s", exc)
                    self._fallback = True
                    return None
                self._scratch = Path(tempfile.mkdtemp(prefix="studio-screengrab-"))
                self.helper = Helper([str(path)], self._scratch / "frame.bgra", self.timeout)
            return self.helper

    async def _failed(self, exc: HelperError) -> None:
        """A helper call failed: start it afresh next time, or after MAX_FAILURES in a row, give it up."""
        self._failures += 1
        helper = self.helper
        if self._failures >= self.MAX_FAILURES:
            log.warning("screengrab failed %d times in a row (%s); screenshots through screencapture from now on",
                        self._failures, exc)
            self.helper, self._fallback = None, True
        else:
            log.warning("screengrab: %s", exc)
        if helper is not None:
            await helper.close()
