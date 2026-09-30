#!/usr/bin/env python3
"""
live.py - Dependency-free OSC client + library for driving Ableton Live 12
(release build) via the AbletonOSC MIDI Remote Script.

AbletonOSC listens on UDP 11000 and sends replies to UDP 11001. Only `/live/.../get/*`
addresses (and active listeners) send a reply; `set/*` and method calls are
fire-and-forget (no reply).

CLI usage:
    live.py <address> [args...]          # send one OSC message, print any reply
    live.py --timeout 3 /live/song/get/tempo
    live.py /live/song/set/tempo 128     # no reply expected
    live.py --batch < commands.txt       # one message per line, sequential
    live.py --listen /live/song/get/beat # subscribe; print updates until Ctrl-C

Arg typing: bare tokens are parsed as int, then float, else string.
Force a type with a prefix:  i:42  f:3.14  s:120  (s: keeps it a string)

Library usage:
    from live import Live
    live = Live()
    live.get("/live/song/get/tempo")          -> [128.0]
    live.set("/live/song/set/tempo", 140)     -> None (fire-and-forget)
    live.call("/live/song/start_playing")
    tempo = live.song_tempo()
"""
import argparse
import socket
import struct
import sys
import time
from typing import Any, List, Optional, Sequence, Tuple

DEFAULT_HOST = "127.0.0.1"
SEND_PORT = 11000
RECV_PORT = 11001


# ----------------------------------------------------------------------------
# Minimal OSC 1.0 encode / decode (no external deps)
# ----------------------------------------------------------------------------
def _pad(b: bytes) -> bytes:
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def encode(address: str, args: Sequence[Any]) -> bytes:
    msg = _pad(address.encode("utf-8") + b"\x00")
    typetags = ","
    payload = b""
    for a in args:
        if isinstance(a, bool):
            typetags += "T" if a else "F"
        elif isinstance(a, int):
            typetags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            typetags += "f"
            payload += struct.pack(">f", a)
        elif isinstance(a, bytes):
            typetags += "b"
            payload += struct.pack(">i", len(a)) + _pad(a)
        else:
            typetags += "s"
            payload += _pad(str(a).encode("utf-8") + b"\x00")
    return msg + _pad(typetags.encode("utf-8") + b"\x00") + payload


def decode(data: bytes) -> Tuple[str, List[Any]]:
    end = data.index(b"\x00")
    address = data[:end].decode("utf-8", "replace")
    i = (end // 4 + 1) * 4
    if i >= len(data) or data[i:i + 1] != b",":
        return address, []
    tt_end = data.index(b"\x00", i)
    typetags = data[i + 1:tt_end].decode("utf-8", "replace")
    p = (tt_end // 4 + 1) * 4
    args: List[Any] = []
    for t in typetags:
        if t == "i":
            args.append(struct.unpack(">i", data[p:p + 4])[0]); p += 4
        elif t == "f":
            args.append(struct.unpack(">f", data[p:p + 4])[0]); p += 4
        elif t == "d":
            args.append(struct.unpack(">d", data[p:p + 8])[0]); p += 8
        elif t == "h":
            args.append(struct.unpack(">q", data[p:p + 8])[0]); p += 8
        elif t == "s" or t == "S":
            e = data.index(b"\x00", p)
            args.append(data[p:e].decode("utf-8", "replace"))
            p = (e // 4 + 1) * 4
        elif t == "b":
            n = struct.unpack(">i", data[p:p + 4])[0]; p += 4
            args.append(data[p:p + n]); p += (n + 3) // 4 * 4
        elif t == "T":
            args.append(True)
        elif t == "F":
            args.append(False)
        elif t == "N":
            args.append(None)
        # 'I' (infinitum), etc. ignored
    return address, args


def coerce_arg(token: str) -> Any:
    if len(token) >= 2 and token[1] == ":":
        kind, rest = token[0], token[2:]
        if kind == "i":
            return int(rest)
        if kind == "f":
            return float(rest)
        if kind == "s":
            return rest
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


# ----------------------------------------------------------------------------
# Live client
# ----------------------------------------------------------------------------
class LiveError(Exception):
    pass


class Live:
    def __init__(self, host: str = DEFAULT_HOST, send_port: int = SEND_PORT,
                 recv_port: int = RECV_PORT, timeout: float = 3.0):
        self.host = host
        self.send_port = send_port
        self.recv_port = recv_port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def _socket(self) -> socket.socket:
        if self._sock is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind((self.host if self.host != "0.0.0.0" else "", self.recv_port))
            self._sock = s
        return self._sock

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def send(self, address: str, *args: Any) -> None:
        """Fire-and-forget: send an OSC message, do not wait for a reply."""
        self._socket().sendto(encode(address, args), (self.host, self.send_port))

    def request(self, address: str, *args: Any,
                timeout: Optional[float] = None,
                match: Optional[str] = None) -> List[Any]:
        """Send and wait for a reply whose address == `match` (default: `address`).
        Returns the reply args. Raises LiveError on timeout."""
        match = match or address
        s = self._socket()
        # drain any stale datagrams
        s.setblocking(False)
        try:
            while True:
                s.recvfrom(65536)
        except (BlockingIOError, OSError):
            pass
        s.setblocking(True)
        s.settimeout(timeout if timeout is not None else self.timeout)
        s.sendto(encode(address, args), (self.host, self.send_port))
        deadline = time.time() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise LiveError("timeout waiting for reply to %s" % address)
            s.settimeout(remaining)
            try:
                data, _ = s.recvfrom(65536)
            except socket.timeout:
                raise LiveError("timeout waiting for reply to %s" % address)
            addr, reply = decode(data)
            if addr == match:
                return reply
            # otherwise keep waiting (could be a stray listener update)

    # convenience aliases -----------------------------------------------------
    def get(self, address: str, *args: Any, timeout: Optional[float] = None) -> List[Any]:
        return self.request(address, *args, timeout=timeout)

    def set(self, address: str, *args: Any) -> None:
        self.send(address, *args)

    def call(self, address: str, *args: Any) -> None:
        self.send(address, *args)

    def listen(self, address: str, *args: Any):
        """Generator yielding (address, args) for updates on `address`.
        Sends start_listen at `address` then yields incoming datagrams for it."""
        s = self._socket()
        s.sendto(encode(address, args), (self.host, self.send_port))
        s.setblocking(True)
        while True:
            s.settimeout(None)
            data, _ = s.recvfrom(65536)
            yield decode(data)

    # high-level helpers ------------------------------------------------------
    def ping(self) -> bool:
        try:
            return self.request("/live/test")[0] == "ok"
        except LiveError:
            return False

    def version(self) -> str:
        v = self.request("/live/application/get/version")
        return ".".join(str(x) for x in v)

    def song_tempo(self) -> float:
        return self.request("/live/song/get/tempo")[0]

    def num_tracks(self) -> int:
        return self.request("/live/song/get/num_tracks")[0]

    def track_names(self) -> List[str]:
        return self.request("/live/song/get/track_names")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _fmt(args: List[Any]) -> str:
    return "\t".join("" if a is None else str(a) for a in args)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="OSC client for Ableton Live via AbletonOSC")
    p.add_argument("address", nargs="?", help="OSC address, e.g. /live/song/get/tempo")
    p.add_argument("args", nargs="*", help="OSC arguments (int/float/string auto-typed; i:/f:/s: to force)")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--send-port", type=int, default=SEND_PORT)
    p.add_argument("--recv-port", type=int, default=RECV_PORT)
    p.add_argument("--timeout", type=float, default=3.0, help="reply timeout in seconds")
    p.add_argument("--wait", action="store_true", help="always wait for a reply (default: only for /get/ addresses)")
    p.add_argument("--no-wait", action="store_true", help="never wait for a reply")
    p.add_argument("--json", action="store_true", help="print reply as JSON array")
    p.add_argument("--listen", action="store_true", help="subscribe to `address` and stream updates")
    p.add_argument("--batch", action="store_true", help="read one message per line from stdin")
    a = p.parse_args(argv)

    live = Live(a.host, a.send_port, a.recv_port, a.timeout)

    def run_one(address: str, raw_args: List[str]) -> int:
        args = [coerce_arg(t) for t in raw_args]
        wants_reply = a.wait or (("/get/" in address or address == "/live/test"
                                  or address.endswith("/get")) and not a.no_wait)
        if not wants_reply:
            live.send(address, *args)
            return 0
        try:
            reply = live.request(address, *args)
        except LiveError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        if a.json:
            import json
            print(json.dumps(reply))
        else:
            print(_fmt(reply))
        return 0

    if a.listen:
        if not a.address:
            p.error("--listen requires an address")
        args = [coerce_arg(t) for t in a.args]
        try:
            for addr, reply in live.listen(a.address, *args):
                if a.json:
                    import json
                    print(json.dumps([addr] + reply), flush=True)
                else:
                    print("%s\t%s" % (addr, _fmt(reply)), flush=True)
        except KeyboardInterrupt:
            return 0
        finally:
            live.close()
        return 0

    if a.batch:
        rc = 0
        for line in sys.stdin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            rc |= run_one(parts[0], parts[1:])
        live.close()
        return rc

    if not a.address:
        p.error("address required")
    rc = run_one(a.address, a.args)
    live.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
