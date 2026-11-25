"""Band levels as dB: the one conversion from the meter's RMS values (zpkt.live.meter) to what the Hear bar draws."""

from __future__ import annotations

import math
from collections.abc import Sequence

BAND_COUNT = 31  # the meter's third-octave bands, from 20 Hz up
BASE_HZ = 20.0
RATIO = 2 ** (1 / 3)  # a third of an octave
SILENCE_DB = -140.0  # what a level at or under FLOOR shows
FLOOR = 1e-7  # an RMS level this small or smaller is silence


def rms_to_db(levels: Sequence[float]) -> list[float]:
    """Each RMS level (1.0 is full scale) as dB with two decimals; silence is SILENCE_DB."""
    return [round(20 * math.log10(v), 2) if v > FLOOR else SILENCE_DB for v in levels]


def band_centers() -> list[float]:
    """The centre frequency of each band, in Hz. The meter (zpkt.live.meter) uses the same bands."""
    return [BASE_HZ * RATIO**k for k in range(BAND_COUNT)]
