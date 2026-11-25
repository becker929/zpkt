"""Reading the desk's live meter: a Max for Live device on Main sends 31 third-octave RMS levels as OSC over UDP.

The device is built by contrib/mixdesk/meter.py ("zpkt desk meter"). This module only parses what it sends and reads
a datagram from a socket the caller hands in. It never opens a socket: the app owns the meter's UDP socket
(zpkt.app.connections). Turning levels into dB is zpkt.audio's job (zpkt.audio.levels).
"""

from __future__ import annotations

import struct
from typing import Any, Protocol

METER_PORT = 8987  # where the device sends, and where the app listens
BANDS = 31
BASE_HZ = 20.0
RATIO = 2 ** (1 / 3)  # a third of an octave
_ADDRESS = b"/spec\x00"
_ADDRESS_END = 8  # "/spec" padded to 8 bytes


class DatagramSource(Protocol):
    """What `read_levels` needs of a socket: UDP's `recvfrom`."""

    def recvfrom(self, size: int, /) -> tuple[bytes, Any]: ...


def centers() -> list[float]:
    """The centre frequency of each band, in Hz."""
    return [BASE_HZ * RATIO**k for k in range(BANDS)]


def parse(data: bytes) -> list[float] | None:
    """An OSC "/spec f f ..." message as its numbers; None for anything else, however it is broken."""
    if not data.startswith(_ADDRESS):
        return None
    try:
        end = data.index(b"\x00", _ADDRESS_END)
        tags = data[_ADDRESS_END + 1 : end].decode()
        i = (end + 4) & ~3
        values: list[float] = []
        for tag in tags:
            if tag == "f":
                values.append(struct.unpack(">f", data[i : i + 4])[0])
            elif tag == "i":
                values.append(float(struct.unpack(">i", data[i : i + 4])[0]))
            else:
                return None
            i += 4
    except (ValueError, struct.error):
        return None
    return values


def read_levels(source: DatagramSource) -> list[float] | None:
    """Wait for one datagram from the handed-in socket and parse it; None if it is not a meter message."""
    data, _ = source.recvfrom(4096)
    return parse(data)
