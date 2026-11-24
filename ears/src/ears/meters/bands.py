"""Every frequency band mlab measures in, defined once, with the instruments that use it.

Each meter answers its own question, so there are several band schemes, and they are not interchangeable. "sub"
is 20-60 Hz in the tonal groups and the regions here, but 20-150 Hz in ears' band shares (ears/src/ears/loudness.py).

| Scheme | Bands | Used by |
|---|---|---|
| THIRD_OCTAVE_CENTRES | 30 IEC base-10 1/3-octave bands, 25 Hz-20 kHz | spectrum.third_octave, target, eqfit |
| TONAL_GROUPS | 7 plain-language groups, sub 20-60 to air 8-20k | spectrum.tonal_balance (sheet `tonal.group.*`) |
| REGIONS | 8 regions that tile 20 Hz-20 kHz, then 4 that overlap them | target, eqfit |
| SIDE_MID_EDGES | the edges of the first 8 regions | target side minus mid |
| STEREO_EDGES | 5 bands, 20 Hz-20 kHz | spectrum.stereo_by_band (sheet `stereo.*`) |
| LOW_END_HZ | 20-120 Hz | premaster low-end correlation |
| KICK_LOWPASS_HZ, HATS_HZ | under 100 Hz; 2-16 kHz | sections: kick and hats per bar |
| SCORE_HZ | the 1/3-octave bands from 31.5 Hz to 16 kHz | target and eqfit scores |
| DITHER_TILT_LOW_HZ, DITHER_TILT_HIGH_HZ | 1-5 kHz against 15-20 kHz | bitdepth noise-shape tilt |
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from .arrays import FloatArray

# ------------------------------------------------------------------ 1/3 octaves
THIRD_OCTAVE_CENTRES: FloatArray = 1000.0 * 10 ** (np.arange(-16, 14) / 10)  # 25 Hz .. 20 kHz, 30 bands
NOMINAL = [
    "25",
    "31.5",
    "40",
    "50",
    "63",
    "80",
    "100",
    "125",
    "160",
    "200",
    "250",
    "315",
    "400",
    "500",
    "630",
    "800",
    "1k",
    "1.25k",
    "1.6k",
    "2k",
    "2.5k",
    "3.15k",
    "4k",
    "5k",
    "6.3k",
    "8k",
    "10k",
    "12.5k",
    "16k",
    "20k",
]  # IEC nominal names of THIRD_OCTAVE_CENTRES
SCORE_HZ = (31.5, 16000.0)  # 1/3-octave bands that count in scores


def third_octave_edges(centres: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Lower and upper edges of 1/3-octave bands: centre / 10^0.05 and centre * 10^0.05."""
    return centres / 10**0.05, centres * 10**0.05


def third_octave_width(centres: FloatArray) -> FloatArray:
    """Bandwidth in Hz of 1/3-octave bands."""
    return centres * (10**0.05 - 10**-0.05)


def third_octave_grid(sr: float) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Centres, lower and upper edges of the 1/3-octave bands that fit under Nyquist."""
    _, upper = third_octave_edges(THIRD_OCTAVE_CENTRES)
    centres = THIRD_OCTAVE_CENTRES[upper <= sr / 2]
    lower, upper = third_octave_edges(centres)
    return centres, lower, upper


def nominal(hz: float) -> str:
    """Nominal name of a 1/3-octave centre: 31.6 -> '31.5', 1258.9 -> '1.25k'; other frequencies as '%g'."""
    i = int(np.argmin(np.abs(np.log(THIRD_OCTAVE_CENTRES / hz))))
    return NOMINAL[i] if abs(np.log(THIRD_OCTAVE_CENTRES[i] / hz)) < 0.05 else f"{hz:g}"


def hz_text(hz: float) -> str:
    """A frequency for people: '31.5 Hz', '1.25 kHz'."""
    n = nominal(hz)
    return n[:-1] + " kHz" if n.endswith("k") else n + " Hz"


def in_score(hz: float) -> bool:
    """Whether a 1/3-octave centre is one of the bands SCORE_HZ counts (6 % slack for rounded centres)."""
    return SCORE_HZ[0] / 1.06 <= hz <= SCORE_HZ[1] * 1.06


# ------------------------------------------------------------------ named regions
TONAL_GROUPS: dict[str, tuple[int, int]] = {  # plain-language regions used in the guides
    "sub": (20, 60),
    "bass": (60, 250),
    "low_mid": (250, 500),
    "mid": (500, 2000),
    "upper_mid": (2000, 4000),
    "presence": (4000, 8000),
    "air": (8000, 20000),
}


class Region(NamedTuple):
    """A named stretch of the spectrum that target reports in dB rel LUFS."""

    key: str
    label: str
    lo_hz: int
    hi_hz: int


# The first eight tile 20 Hz-20 kHz; side/mid uses their edges.
REGIONS: list[Region] = [
    Region("sub", "sub 20-60", 20, 60),
    Region("bass", "bass 60-120", 60, 120),
    Region("low_mids", "low mids 120-300", 120, 300),
    Region("mud", "mud 300-600", 300, 600),
    Region("mids", "mids 600-1.5k", 600, 1500),
    Region("upper_mids", "upper mids 1.5-4k", 1500, 4000),
    Region("presence", "presence 4-8k", 4000, 8000),
    Region("air", "air 8-20k", 8000, 20000),
    Region("deep_sub", "deep sub 20-48", 20, 48),
    Region("kick_body", "kick/bass body 55-120", 55, 120),
    Region("bite", "bite 1-4k", 1000, 4000),
    Region("air_8_14k", "air 8-14k", 8000, 14000),
]
REGION_KEYS = [region.key for region in REGIONS]
REGION_LABELS = {region.key: region.label for region in REGIONS}
SIDE_MID_EDGES = (20, 60, 120, 300, 600, 1500, 4000, 8000, 20000)
SIDE_MID_KEYS = REGION_KEYS[:8]


def region_edges(sr: float) -> tuple[FloatArray, FloatArray]:
    """Lower and upper edges of REGIONS in Hz, the upper ones capped at Nyquist."""
    lo = np.array([region.lo_hz for region in REGIONS], float)
    return lo, np.minimum([region.hi_hz for region in REGIONS], sr / 2)


# ------------------------------------------------------------------ detector and check bands
STEREO_EDGES = (20, 120, 500, 2000, 8000, 20000)
LOW_END_HZ = (20, 120)
KICK_LOWPASS_HZ = 100.0
HATS_HZ = (2000.0, 16000.0)
DITHER_TILT_LOW_HZ = (1000, 5000)
DITHER_TILT_HIGH_HZ = (15000, 20000)
