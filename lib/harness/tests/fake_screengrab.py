"""A stand-in for the screengrab helper: the same line protocol over stdin/stdout, on a 64 x 48 screen.

Frames are BGRA with padded rows. Each `shot` moves a bright block two pixels to the right; the stream's frame
changes only on `change`, as a real stream changes only when the screen does. Test-only commands: `change`, `die`
(exit without answering), `hang` (never answer). Environment: FAKE_PREFLIGHT=0 (no Screen Recording),
FAKE_SHOT_FAILS=1 (`shot` answers with an error), FAKE_LOG=<file> (append each launch and command to it).
"""

import json
import os
import sys
import time

W, H, BPR = 64, 48, 64 * 4 + 16


def say(**msg):
    msg.setdefault("ok", True)
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def log(line):
    if os.environ.get("FAKE_LOG"):
        with open(os.environ["FAKE_LOG"], "a") as f:
            f.write(line + "\n")


def frame(n):
    """BGRA rows: dark grey, with a bright orange block at x = 2n (R=250, G=120, B=10)."""
    rows = bytearray(BPR * H)
    for y in range(H):
        for x in range(W):
            i = y * BPR + 4 * x
            lit = 10 <= y < 30 and 2 * n <= x < 2 * n + 16
            rows[i:i + 4] = bytes((10, 120, 250, 255)) if lit else bytes((40, 40, 40, 255))
    return bytes(rows)


def write(path, n):
    with open(path, "wb") as f:
        f.write(frame(n))


def main():
    log(f"launched {os.getpid()}")
    say(ready=True, preflight=os.environ.get("FAKE_PREFLIGHT") != "0", display={"w": W, "h": H})
    shots, seq, streaming = 0, 0, False
    for line in sys.stdin:
        cmd, _, arg = line.strip().partition(" ")
        log(line.strip())
        if cmd == "shot":
            if os.environ.get("FAKE_SHOT_FAILS") == "1":
                say(ok=False, cmd=cmd, error="the display is asleep")
                continue
            shots += 1
            write(arg, shots)
            say(cmd=cmd, w=W, h=H, bpr=BPR)
        elif cmd == "start":
            streaming, seq = True, seq + 1
            say(cmd=cmd, fps=int(arg))
        elif cmd == "frame":
            if not streaming:
                say(ok=False, cmd=cmd, error="no stream (send: start FPS)")
                continue
            write(arg, 10 + seq)
            say(cmd=cmd, w=W, h=H, bpr=BPR, seq=seq)
        elif cmd == "change":
            seq += 1
            say(cmd=cmd)
        elif cmd == "stop":
            streaming = False
            say(cmd=cmd)
        elif cmd == "front":
            say(cmd=cmd, bounds=[8, 4, 32, 24])
        elif cmd == "die":
            sys.exit(3)
        elif cmd == "hang":
            time.sleep(3600)
        else:
            say(ok=False, cmd=cmd, error=f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
