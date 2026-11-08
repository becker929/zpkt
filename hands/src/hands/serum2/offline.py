"""Serum 2 offline through pedalboard: load a state, read/set parameters, render a check.

Needs the `serum` extra (pedalboard, mido). Parameter changes reach the saved state only after
Serum processes audio, so `set` renders a short silent block. The stderr noise
"can't open Tables/..." appears only if the factory content is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

VST3 = "/Library/Audio/Plug-Ins/VST3/Serum2.vst3"
SR = 48000
_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _juce_b64_decode(s: str) -> bytes:
    size_s, data = s.split(".", 1)
    out = bytearray(int(size_s))
    bit = 0
    for ch in data:
        v = _B64.index(ch)
        for b in range(6):
            if bit >= len(out) * 8:
                break
            if v & (1 << b):
                out[bit >> 3] |= 1 << (bit & 7)
            bit += 1
    return bytes(out)


def _juce_b64_encode(b: bytes) -> str:
    nbits, chars = len(b) * 8, []
    for i in range(0, nbits, 6):
        v = sum(1 << j for j in range(6) if i + j < nbits and b[(i + j) >> 3] & (1 << ((i + j) & 7)))
        chars.append(_B64[v])
    return "%d.%s" % (len(b), "".join(chars))


@dataclass
class Check:
    peak: float
    rms_db: float
    centroid_hz: int


class Serum:
    def __init__(self) -> None:
        import pedalboard

        plugin: Any = pedalboard.load_plugin(VST3, plugin_name="Serum 2")
        self.p = plugin
        self.by_name = {v.name: v for v in self.p.parameters.values()}

    # -- state (IComponent, IEditController) as Live stores them
    def state(self) -> tuple[bytes, bytes]:
        xml = self.p.raw_state[8:].decode("utf-8", "replace")
        comp = re.search(r"<IComponent>([^<]*)</IComponent>", xml)
        if comp is None:
            raise ValueError("no IComponent in Serum's state")
        ctl = re.search(r"<IEditController>([^<]*)</IEditController>", xml)
        return _juce_b64_decode(comp.group(1).strip()), _juce_b64_decode(ctl.group(1).strip()) if ctl else b""

    def load(self, processor: bytes, controller: bytes | None = None) -> None:
        import struct

        ctl = controller if controller is not None else self.state()[1]
        xml = ('<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>%s</IComponent>'
               '<IEditController>%s</IEditController></VST3PluginState>'
               % (_juce_b64_encode(processor), _juce_b64_encode(ctl))).encode() + b"\x00"
        self.p.raw_state = b"VC2!" + struct.pack("<I", len(xml)) + xml
        self._commit()

    def _commit(self) -> None:
        self.p([], duration=0.03, sample_rate=SR, buffer_size=512, reset=False)

    def get(self, name: str) -> float:
        return float(self.by_name[name].raw_value)

    def set(self, name: str, raw: float) -> None:
        self.by_name[name].raw_value = min(1.0, max(0.0, raw))
        self._commit()

    def render(self, notes=((69, 0.0, 0.6), (72, 0.0, 0.6)), dur: float = 2.0, vel: int = 110) -> np.ndarray:
        from mido import Message

        msgs = []
        for pitch, start, length in notes:
            msgs += [Message("note_on", note=pitch, velocity=vel, time=start),
                     Message("note_off", note=pitch, velocity=0, time=start + length)]
        msgs.sort(key=lambda m: m.time)
        self.p.reset()
        return self.p(msgs, duration=dur, sample_rate=SR, buffer_size=512)


def check(audio: np.ndarray) -> Check:
    m = audio.mean(axis=0)
    f = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    hz = np.fft.rfftfreq(len(m), 1 / SR)
    return Check(round(float(np.abs(audio).max()), 3),
                 round(float(20 * np.log10(np.sqrt((audio ** 2).mean()) + 1e-9)), 1),
                 int((f * hz).sum() / max(f.sum(), 1e-12)))
