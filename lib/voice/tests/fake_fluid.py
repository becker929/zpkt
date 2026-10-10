"""A stand-in for the kokoro-fluid helper: the same frames, a tone for speech, padded with silence like the real one.

    python fake_fluid.py LOG [MODE]

Each request is appended to LOG as a JSON line. MODE: "ok" (the default), "dead" (exits before it is ready), or
"die-after-N" (exits after answering N requests)."""

import json
import struct
import sys

import numpy as np

from voice import protocol

RATE = 24_000


def frame(stdin):
    head = stdin.read(4)
    if len(head) < 4:
        return None
    header = json.loads(stdin.read(struct.unpack(">I", head)[0]))
    stdin.read(struct.unpack(">I", stdin.read(4))[0])
    return header


def speech(text: str, speed: float) -> np.ndarray:
    """0.3 s of silence, a tone 30 ms a character (over the speed), then 0.5 s of silence."""
    t = np.arange(int(len(text) * 0.03 / speed * RATE)) / RATE
    tone = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    return np.concatenate([np.zeros(int(0.3 * RATE), np.int16), tone, np.zeros(int(0.5 * RATE), np.int16)])


def main() -> None:
    log, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "ok")
    if mode == "dead":
        sys.exit(2)
    out = sys.stdout.buffer
    out.write(protocol.encode({"op": "ready", "rate": RATE, "load_ms": 1, "warmup_ms": 1}))
    out.flush()
    answered = 0
    while (request := frame(sys.stdin.buffer)) is not None:
        with open(log, "a") as f:
            f.write(json.dumps(request) + "\n")
        if mode.startswith("die-after-") and answered >= int(mode.rsplit("-", 1)[1]):
            sys.exit(1)
        if "#" in request["text"]:
            out.write(protocol.encode({"op": "error", "id": request["id"], "msg": "nothing to say"}))
        else:
            pcm = speech(request["text"], request["speed"])
            out.write(protocol.encode({"op": "audio", "id": request["id"], "rate": RATE, "ms": 1, "mb": 1},
                                      pcm.astype("<i2").tobytes()))
        out.flush()
        answered += 1


if __name__ == "__main__":
    main()
