"""
Tiny sanity/regression tests for synth.engine.

Run with:
    python3 -m pytest synth/test_engine.py
or:
    python3 synth/test_engine.py
"""

import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synth import engine
from synth.engine import SR


def _spectrum(x, sr=SR):
    n = len(x)
    mag = np.abs(np.fft.rfft(x * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    return freqs, mag


def _centroid(x, sr=SR):
    freqs, mag = _spectrum(x, sr)
    return float(np.sum(freqs * mag) / (np.sum(mag) + 1e-12))


def _dominant_freq(x, sr=SR):
    freqs, mag = _spectrum(x, sr)
    return float(freqs[np.argmax(mag)])


def test_finite_and_peak():
    for arr in [engine.kick(), engine.rumble(engine.kick()), engine.hat(),
                engine.clap(), engine.ride_or_perc(), engine.stab(),
                engine.pad(length_ms=500), engine.riser(length_ms=500),
                engine.impact()]:
        assert np.all(np.isfinite(arr))
        assert np.max(np.abs(arr)) <= 1.0 + 1e-6


def test_lengths():
    n = engine.kick(length_ms=300)
    assert abs(len(n) / SR * 1000 - 300) < 2
    n2 = engine.pad(length_ms=1000)
    assert abs(len(n2) / SR * 1000 - 1000) < 2
    n3 = engine.riser(length_ms=2000)
    assert abs(len(n3) / SR * 1000 - 2000) < 2


def test_kick_pitch_settles_near_end_freq():
    pitch_end = 45
    k = engine.kick(pitch_end_hz=pitch_end, pitch_decay_ms=35, amp_decay_ms=300,
                     length_ms=450, click_level=0.0)
    # analyse the tail, well after the pitch sweep has settled
    start = int(0.15 * SR)
    tail = k[start:]
    freq = _dominant_freq(tail)
    assert abs(freq - pitch_end) < 10, f"dominant freq {freq} not near {pitch_end}"


def test_kick_centroid_is_low():
    k = engine.kick()
    c = _centroid(k)
    assert c < 400, f"kick centroid {c} Hz not < 400 Hz"


def test_closed_hat_centroid_is_high():
    h = engine.hat(closed=True)
    c = _centroid(h)
    assert c > 5000, f"closed hat centroid {c} Hz not > 5 kHz"


def test_rumble_energy_below_lowpass():
    lp = 160
    r = engine.rumble(engine.kick(), lowpass_hz=lp)
    freqs, mag = _spectrum(r)
    power = mag ** 2
    below = np.sum(power[freqs <= lp])
    total = np.sum(power) + 1e-12
    ratio = below / total
    assert ratio > 0.7, f"only {ratio:.2f} of rumble energy below {lp} Hz"


def test_determinism():
    a1 = engine.kick(pitch_end_hz=50)
    a2 = engine.kick(pitch_end_hz=50)
    assert np.array_equal(a1, a2)

    b1 = engine.hat(closed=False)
    b2 = engine.hat(closed=False)
    assert np.array_equal(b1, b2)

    c1 = engine.clap()
    c2 = engine.clap()
    assert np.array_equal(c1, c2)

    import synth.presets as presets
    l1, s1 = presets.hard_techno_bar(variant="drop")
    l2, s2 = presets.hard_techno_bar(variant="drop")
    assert np.array_equal(l1, l2)
    for k in s1:
        assert np.array_equal(s1[k], s2[k])


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    if failed:
        print(f"{failed} test(s) failed")
        sys.exit(1)
    print("All tests passed.")
