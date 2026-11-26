"""What a capture is (Source, Stream), the screen capture, and the chain that tries one source and then the next.

The screen capture is a tool built from capture.swift on first use, run as a process that writes PCM on its standard
output.

The binary is never in the repo. It is compiled into the rig's cache folder (`<data_dir>/cache/listen`, or
`ZPKT_LISTEN_DIR`) and named by the hash of its source, so an edit to the source builds a new one.
"""

from __future__ import annotations

import hashlib
import os
import select
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from zpkt.live import config

SOURCE = Path(__file__).resolve().parent / "capture.swift"
EXIT_PERMISSION = 77
EXIT_NO_APP = 78
START_WAIT_S = 10.0  # the tool itself gives up after 6
SCREEN_RATE = 48_000  # what capture.swift asks macOS for
PERMISSION = (
    "The Mac has not allowed zpkt to record Live's sound. On the Mac, open System Settings, Privacy & Security, "
    "Screen & System Audio Recording, and turn it on for the app that starts zpkt ({app}). Then tap Listen again."
)
NOT_RUNNING = "Live is not running on the Mac, so there is nothing to hear."
NOT_A_MAC = "Listening needs the Mac that runs Live. This computer is not a Mac."
NO_SWIFT = (
    "The Mac has no Swift compiler, so the capture tool cannot be built. Install Xcode's command line tools "
    "(xcode-select --install) and tap Listen again."
)


class Unavailable(Exception):
    """Capture cannot start; the message is for the page, in plain words."""


class Stream(Protocol):
    """A running capture: 16-bit little-endian stereo at `rate`, which stays the same for as long as it runs."""

    rate: int
    source: str  # which capture it is, for the status: "live device" or "screen capture"

    def read(self) -> bytes:
        """The next piece of PCM, waiting for it; b"" when the capture has ended."""
        ...

    def close(self) -> None: ...


class Source(Protocol):
    """Where the sound comes from."""

    name: str  # what the status calls it; a chain says which of its sources last worked, "" when none has
    rate: int  # the sample rate its next capture is expected to have (a guess until one has run or been checked)

    def check(self) -> str:
        """ "" when capture can start, else the reason in plain words."""
        ...

    def open(self) -> Stream:
        """Start capturing. Raises Unavailable."""
        ...


def cache_dir(env: Mapping[str, str] = os.environ) -> Path:
    named = env.get("ZPKT_LISTEN_DIR")
    return Path(named).expanduser() if named else config.rig().data_dir / "cache" / "listen"


def responsible_app() -> str:
    """The app macOS holds responsible for this process: the one whose permission counts. "" when unknown."""
    try:
        import ctypes

        fn = ctypes.CDLL("/usr/lib/libSystem.B.dylib").responsibility_get_pid_responsible_for_pid
        fn.restype = ctypes.c_int
        pid = fn(os.getpid())
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, AttributeError, subprocess.SubprocessError):
        return ""
    path = out.strip()
    app = next((part for part in path.split("/") if part.endswith(".app")), "")
    return app.removesuffix(".app") or Path(path).name


class ProcessStream:
    """The tool as a child process; its standard output is the sound."""

    rate = SCREEN_RATE
    source = "screen capture"

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self.proc = proc
        assert proc.stdout is not None
        self.fd = proc.stdout.fileno()

    def read(self) -> bytes:
        """Only one thread reads. It closes the pipe itself at the end, so `close` never pulls it from under a read."""
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data and self.proc.stdout is not None and not self.proc.stdout.closed:
            self.proc.stdout.close()
        return data

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


class SwiftCapture:
    """The real source: capture.swift, compiled once, recording one application (Live).

    macOS lets the app that started zpkt hold one such capture at a time: a second one cuts the first off, and two
    that start in the same moment can leave one waiting for ever. So starts are taken one at a time here, the tool
    gives up a start that does not come, and the hub starts a capture again when it is cut off."""

    name = "screen capture"
    rate = SCREEN_RATE

    def __init__(
        self,
        folder: Path | None = None,
        bundle: str = "com.ableton.live",
        platform: str = sys.platform,
        which: Callable[[str], str | None] = shutil.which,
        args: Sequence[str] = (),
    ) -> None:
        self.args = list(args)  # more arguments for the tool ("--all": everything the Mac plays, for testing)
        self.folder = folder
        self.bundle = bundle
        self.platform = platform
        self.which = which
        self._lock = threading.Lock()
        self._one = threading.Lock()  # one run of the tool starts at a time: two starting together block each other

    def binary(self) -> Path:
        """The built tool, building it if this source has no binary yet. Raises Unavailable."""
        if self.platform != "darwin":
            raise Unavailable(NOT_A_MAC)
        folder = self.folder or cache_dir()
        digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()[:12]
        out = folder / f"zpkt-listen-capture-{digest}"
        with self._lock:
            if out.is_file():
                return out
            if not self.which("xcrun"):
                raise Unavailable(NO_SWIFT)
            folder.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(f".{os.getpid()}.tmp")
            done = subprocess.run(
                ["xcrun", "swiftc", "-O", "-swift-version", "5", "-o", str(tmp), str(SOURCE)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if done.returncode != 0:
                tmp.unlink(missing_ok=True)
                if "unable to find utility" in done.stderr or "command line tools" in done.stderr.lower():
                    raise Unavailable(NO_SWIFT)
                raise Unavailable("The capture tool did not build: " + done.stderr.strip()[-300:])
            tmp.replace(out)
            for old in folder.glob("zpkt-listen-capture-*"):
                if old != out:
                    old.unlink(missing_ok=True)
            return out

    def _reason(self, code: int, said: str) -> str:
        if code == EXIT_PERMISSION:
            return PERMISSION.format(app=responsible_app() or "the terminal or app it was started from")
        if code == EXIT_NO_APP:
            return NOT_RUNNING
        return "The capture tool stopped: " + (said.strip().splitlines() or ["no reason given"])[-1]

    def check(self) -> str:
        try:
            tool = self.binary()
        except Unavailable as exc:
            return str(exc)
        with self._one:
            return self._check(tool)

    def _check(self, tool: Path) -> str:
        try:
            done = subprocess.run(
                [str(tool), "--bundle", self.bundle, *self.args, "--check"], capture_output=True, text=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"The capture tool did not run: {exc}"
        return "" if done.returncode == 0 else self._reason(done.returncode, done.stderr)

    def open(self) -> Stream:
        """Start the tool. macOS now and then never answers its request to start; the tool then gives up after six
        seconds and one more try is made here."""
        tool = self.binary()
        with self._one:
            return self._open(tool)

    def _open(self, tool: Path) -> Stream:
        reason = ""
        for _ in range(2):
            try:
                proc = subprocess.Popen(
                    [str(tool), "--bundle", self.bundle, *self.args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except OSError as exc:
                raise Unavailable(f"The capture tool did not run: {exc}") from exc
            assert proc.stderr is not None
            ready, _, _ = select.select([proc.stderr], [], [], START_WAIT_S)
            first = proc.stderr.readline().decode(errors="replace") if ready else ""  # "capturing ..." or why not
            if first.startswith("capturing"):
                # keep the pipe empty
                threading.Thread(target=proc.stderr.read, daemon=True, name="listen-stderr").start()
                return ProcessStream(proc)
            if proc.poll() is None and not first:
                proc.kill()
            try:
                code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = -1
            ProcessStream(proc).close()
            reason = self._reason(code, first or "it did not start")
            if code in (EXIT_PERMISSION, EXIT_NO_APP):
                break
        raise Unavailable(reason)


class Chain:
    """Several sources in order of preference: the first that can start is the capture.

    `name` and `rate` are those of the source that last worked (a check or a start), so the status can say which
    capture a listener will get, and at what rate, before anything runs."""

    def __init__(self, sources: Iterable[Source]) -> None:
        self.sources = list(sources)
        if not self.sources:
            raise ValueError("a chain needs at least one source")
        self.name = ""
        self.rate = self.sources[0].rate

    @staticmethod
    def _why(reasons: Sequence[str]) -> str:
        """Every source's reason, the preferred one first: each names its own fix."""
        return " The other way to hear Live did not work either: ".join(reasons)

    def check(self) -> str:
        reasons = []
        for source in self.sources:
            reason = source.check()
            if not reason:
                self.name, self.rate = source.name, source.rate
                return ""
            reasons.append(reason)
        self.name = ""
        return self._why(reasons)

    def open(self) -> Stream:
        reasons = []
        for source in self.sources:
            try:
                stream = source.open()
            except Unavailable as exc:
                reasons.append(str(exc))
                continue
            self.name, self.rate = stream.source, stream.rate
            return stream
        self.name = ""
        raise Unavailable(self._why(reasons))
