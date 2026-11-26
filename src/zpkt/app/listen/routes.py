"""The mount at /app/listen: the status, the stream (raw PCM, or MP3 for a browser that cannot play PCM), the script.

GET /app/listen/status      {"available", "reason", "listeners", "capturing", "format"}
GET /app/listen/stream.pcm  16-bit little-endian stereo at 48 kHz, for as long as the page reads it
GET /app/listen/stream.mp3  the same sound through ffmpeg, for an <audio> element (a second or more late)
GET /app/listen/listen.js   the page's script (also served at /app/shell/listen.js by the shell)
"""

from __future__ import annotations

import contextlib
import json
import select
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from zpkt.app.listen import CHANNELS, RATE
from zpkt.app.listen.capture import Unavailable
from zpkt.app.listen.hub import Hub, Listener
from zpkt.app.mounts import MountReply, Request

SCRIPT = Path(__file__).resolve().parents[1] / "static" / "shell" / "listen.js"
MP3 = ["-c:a", "libmp3lame", "-b:a", "192k", "-flush_packets", "1", "-f", "mp3", "pipe:1"]
NO_FFMPEG = "The Mac has no ffmpeg, so there is no MP3 stream. The PCM stream still works."


def _json(obj: Any, code: int = 200) -> MountReply:
    return MountReply(code, json.dumps(obj).encode())


def _gone(sock: socket.socket) -> bool:
    """True when the page has closed its end (asked only while the capture is quiet, so nothing is being written)."""
    try:
        ready, _, _ = select.select([sock], [], [], 0)
        return bool(ready) and sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


class ListenMount:
    def __init__(self, hub: Hub, ffmpeg: str | None = None) -> None:
        self.hub = hub
        self.ffmpeg = ffmpeg if ffmpeg is not None else (shutil.which("ffmpeg") or "")

    def handle(self, request: Request) -> MountReply | None:
        if request.method not in ("GET", "HEAD"):
            return _json({"ok": False, "error": "Listen only answers GET"}, 405)
        rest = request.rest
        if rest == "/status":
            return _json(self.hub.status())
        if rest == "/listen.js":
            return MountReply(200, SCRIPT.read_bytes(), "text/javascript; charset=utf-8", "no-cache")
        if rest in ("/stream.pcm", "/stream.mp3"):
            mp3 = rest.endswith(".mp3")
            if mp3 and not self.ffmpeg:
                return _json({"ok": False, "error": NO_FFMPEG}, 503)
            ctype = "audio/mpeg" if mp3 else "application/octet-stream"
            if request.method == "HEAD":
                return MountReply(200, b"", ctype)
            try:
                listener = self.hub.join()
            except Unavailable as exc:
                return _json({"ok": False, "error": str(exc)}, 503)
            try:
                self._begin(request.connection, ctype)
                (self._mp3 if mp3 else self._pcm)(request.connection, listener)
            except OSError:  # the page went away
                pass
            finally:
                self.hub.leave(listener)
            return None
        return _json({"ok": False, "error": "not found"}, 404)

    @staticmethod
    def _begin(h: Any, ctype: str) -> None:
        with contextlib.suppress(OSError):
            h.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # small pieces, sent at once
        h.send_response(200)
        for key, value in (
            ("Content-Type", ctype),
            ("Cache-Control", "no-store"),
            ("X-Accel-Buffering", "no"),
            ("X-Audio-Format", f"s16le;rate={RATE};channels={CHANNELS}"),
        ):
            h.send_header(key, value)
        h.end_headers()  # no Content-Length: the answer ends when the connection closes
        h.close_connection = True

    @staticmethod
    def _pcm(h: Any, listener: Listener) -> None:
        while True:
            chunk = listener.get()
            if chunk is None:
                return
            if chunk:
                h.wfile.write(chunk)
            elif _gone(h.connection):
                return

    def _mp3(self, h: Any, listener: Listener) -> None:
        """One ffmpeg per listener: PCM in from the listener's queue, MP3 out to the page."""
        proc = subprocess.Popen(
            [self.ffmpeg, "-v", "quiet", "-f", "s16le", "-ar", str(RATE), "-ac", str(CHANNELS), "-i", "pipe:0", *MP3],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        assert proc.stdin is not None and proc.stdout is not None
        stdin, stdout = proc.stdin, proc.stdout

        def feed() -> None:
            try:
                while proc.poll() is None:
                    chunk = listener.get()
                    if chunk is None:
                        break
                    if chunk:
                        stdin.write(chunk)
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    stdin.close()

        threading.Thread(target=feed, daemon=True, name="listen-mp3").start()
        try:
            while True:
                out = stdout.read(4096)
                if not out:
                    return
                h.wfile.write(out)
        finally:
            proc.kill()
            proc.wait()
            stdout.close()
