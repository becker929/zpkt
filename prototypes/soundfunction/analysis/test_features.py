"""Plain-script tests: `python3 analysis/test_features.py`.

Uses synthetic fixtures only (no real corpus / synth output required).
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from analysis import fixtures
from analysis.signal_features import describe_hit
from analysis.context_features import describe_track, BEAT_BINS, OFFBEAT8_BINS
import tempfile
import soundfile as sf

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def test_sine_burst():
    y, sr = fixtures.sine_burst(freq=50.0)
    f = describe_hit(y, sr)
    check("sine_burst centroid < 200 Hz", f["spectral_centroid_hz"] < 200,
          f'(got {f["spectral_centroid_hz"]:.1f})')
    share = f["band_sub_share"] + f["band_low_share"]
    check("sine_burst sub+low share > 0.8", share > 0.8, f"(got {share:.3f})")


def test_noise_burst():
    y, sr = fixtures.noise_burst()
    f = describe_hit(y, sr)
    check("noise_burst flatness > 0.5", f["spectral_flatness"] > 0.5,
          f'(got {f["spectral_flatness"]:.3f})')
    check("noise_burst centroid > 3000 Hz", f["spectral_centroid_hz"] > 3000,
          f'(got {f["spectral_centroid_hz"]:.1f})')


def test_clicked_sweep_smoke():
    y, sr = fixtures.clicked_sine_sweep()
    f = describe_hit(y, sr)
    ok = all(k in f for k in ("f0_hz_at_5ms", "f0_hz_at_30ms", "f0_hz_at_100ms"))
    check("clicked_sweep describe_hit runs and has pitch-envelope keys", ok)
    p5, p100 = f["f0_hz_at_5ms"], f["f0_hz_at_100ms"]
    if not (np.isnan(p5) or np.isnan(p100)):
        check("clicked_sweep pitch falls from 5ms to 100ms", p5 > p100,
              f"(5ms={p5:.1f}Hz 100ms={p100:.1f}Hz)")
    else:
        print("[SKIP] clicked_sweep pitch-fall check (pyin returned unvoiced frames)")


def test_click_track():
    y, sr, bpm, n_bars = fixtures.click_track()
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        sf.write(tmp.name, y, sr)
        entry = describe_track(tmp.name)

    check("tempo within 2 BPM of 150 (after octave correction)",
          abs(entry["tempo_bpm"] - 150) <= 2,
          f'(raw={entry["tempo_bpm_raw"]:.1f} corrected={entry["tempo_bpm"]:.1f} '
          f'correction={entry["tempo_correction"]})')

    kfpb = entry["kick"]["kick_fraction_per_bar"]
    n = len(kfpb)
    on_bars = list(range(0, min(8, n))) + list(range(12, n))
    off_bars = list(range(8, min(12, n)))
    on_vals = [kfpb[b] for b in on_bars]
    off_vals = [kfpb[b] for b in off_bars]
    check("kick fraction ~1.0 in bars 1-8 & 13-16",
          bool(on_vals) and min(on_vals) >= 0.75, f"(vals={['%.2f' % v for v in on_vals]})")
    check("kick fraction ~0 in bars 9-12",
          bool(off_vals) and max(off_vals) <= 0.25, f"(vals={['%.2f' % v for v in off_vals]})")

    bd = entry["candidate_breakdown"]
    check("candidate breakdown detected", bd is not None, f"(got {bd})")
    if bd:
        overlap = max(0, min(bd["end_bar"], 12) - max(bd["start_bar"], 8))
        check("candidate breakdown overlaps bars 9-12", overlap >= 3,
              f'(breakdown bars {bd["start_bar"]}-{bd["end_bar"]}, overlap={overlap})')

    high_profile = np.array(entry["bands"]["high"]["bar_profile_16step"])
    top4 = set(np.argsort(-high_profile)[:4].tolist())
    check("high band bar-profile peaks on offbeat 8th bins",
          len(top4 & set(OFFBEAT8_BINS)) >= 3,
          f"(top bins={sorted(top4)}, expected subset of {OFFBEAT8_BINS})")


def main():
    tests = [test_sine_burst, test_noise_burst, test_clicked_sweep_smoke, test_click_track]
    for t in tests:
        print(f"--- {t.__name__} ---")
        try:
            t()
        except Exception:
            FAILURES.append(t.__name__)
            print(f"[ERROR] {t.__name__} raised:")
            traceback.print_exc()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()


def test_decay_tracks_decay_not_pitch():
    """decay_ms must measure how long a sound lasts, not its period.

    Regression test. The first version scanned abs(y) for the first sample
    below a threshold after the peak. An oscillating waveform passes near zero
    every half cycle, so it reported the SAME 0.113 ms for a hat with a 15 ms
    tail and one with a 250 ms tail: it was reading pitch, not decay.
    """
    import numpy as np
    from analysis.signal_features import describe_hit

    sr = 44100
    t = np.arange(int(sr * 1.0)) / sr
    tone = np.sin(2 * np.pi * 200.0 * t)

    # Same tone, same pitch, three different decay times.
    decays = [0.02, 0.10, 0.40]
    measured = [describe_hit(tone * np.exp(-t / (d / 3.0)), sr)["decay_ms"] for d in decays]

    assert measured[0] < measured[1] < measured[2], (
        f"decay_ms must rise with decay time, got {measured}")
    # A 20x longer tail must read as clearly longer, not marginally so.
    assert measured[2] > 5 * measured[0], f"decay_ms barely moved: {measured}"

    # Same decay, two different pitches: decay_ms must NOT follow pitch.
    fast = np.sin(2 * np.pi * 2000.0 * t) * np.exp(-t / 0.05)
    slow = np.sin(2 * np.pi * 50.0 * t) * np.exp(-t / 0.05)
    a = describe_hit(fast, sr)["decay_ms"]
    b = describe_hit(slow, sr)["decay_ms"]
    assert abs(a - b) < 0.25 * max(a, b), (
        f"decay_ms changed with pitch alone: {a} vs {b}")


def test_duration_tracks_length_not_pitch():
    """duration_s had the same raw-sample defect as decay_ms."""
    import numpy as np
    from analysis.signal_features import describe_hit

    sr = 44100
    t = np.arange(int(sr * 1.0)) / sr
    short = np.sin(2 * np.pi * 200.0 * t) * np.exp(-t / 0.01)
    long = np.sin(2 * np.pi * 200.0 * t) * np.exp(-t / 0.20)
    assert describe_hit(long, sr)["duration_s"] > 5 * describe_hit(short, sr)["duration_s"]
