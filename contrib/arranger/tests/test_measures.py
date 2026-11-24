"""The measuring scripts on made-up audio: a synthetic kick loop at 160 BPM (a decaying 55 Hz sine with a click on
every beat) and noise. Rounded results are pinned as goldens, so a refactor that changes a number shows up."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from samples import assert_golden

pytest.importorskip("scipy")
pytest.importorskip("pyloudnorm")

RATE = 44100
BEAT = 60 / 160


def kick_loop(beats: int = 64, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = round(beats * BEAT * RATE)
    t = np.arange(int(BEAT * RATE)) / RATE
    hit = 0.8 * np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.12) + 0.2 * rng.standard_normal(len(t)) * np.exp(-t / 0.004)
    x = np.zeros(n)
    for k in range(beats):
        a = round(k * BEAT * RATE)
        m = min(len(hit), n - a)
        x[a : a + m] += hit[:m]
    x += 0.01 * rng.standard_normal(n)  # a little hiss between hits
    return np.stack([x, 0.9 * x], axis=1).astype("float32")


def r(v, places: int = 2):
    return np.round(np.asarray(v, dtype=float), places).tolist()


@pytest.fixture
def loop(tmp_path: Path) -> Path:
    f = tmp_path / "kick.flac"
    sf.write(f, kick_loop(), RATE, subtype="PCM_16")
    return f


def test_mine_features_and_segments():
    import mine

    x = np.concatenate([kick_loop(16), np.zeros((4 * mine.BAR, 2), "float32"), kick_loop(8, seed=2)])
    F, db = mine.features(x)
    segs, thr = mine.segments(F, db > mine.SILENT_DB)
    assert_golden(
        "mine-segments",
        {
            "db": r(db, 1),
            "segments": [list(s) for s in segs],
            "threshold": round(thr, 4),
            "peaks": mine.peaks(x[: 4 * mine.BAR], 4)[:24],
        },
    )


def test_spectral_measure_file(loop):
    import spectral

    m = spectral.measure_file(loop, 6.0, 1.5)
    assert set(m) == {"build", "drop"}
    assert_golden(
        "spectral-measure",
        {
            p: {"spectrum": r(v["spectrum"], 1), "lufs": round(v["lufs"], 1), "side": v["side"], "plr": v["plr"]}
            for p, v in m.items()
        },
    )


def test_kickiso_shape(loop):
    import kickiso

    shape, n = kickiso.shape_of(loop, 0.0, 160.0, beats=48)
    assert_golden("kickiso-shape", {"beats": n, "shape": r(shape, 1)})


def test_kicktexture(loop):
    import kicktexture

    assert_golden("kicktexture", kicktexture.texture(loop, 160.0, exact=True))


def test_kickdesign_frames(loop):
    import kickdesign

    x, rate = sf.read(loop, always_2d=True)
    P, avg = kickdesign.frames_of(x[: int(4 * BEAT * rate)], rate)
    assert_golden(
        "kickdesign-frames",
        {"n": len(P), "avg": r(10 * np.log10(avg / avg.sum()), 1), "b64head": kickdesign.encode(P, avg.sum())[:120]},
    )


def test_kickshape(loop):
    import kickshape

    m, sr = kickshape.mono(loop)
    seg, at = kickshape.kick_alone(m, sr)
    assert_golden(
        "kickshape",
        {
            "thirds": r(kickshape.third_octaves(m, sr), 1),
            "at": round(at, 3),
            "len": len(seg),
            "rms": round(float(kickshape.rms_db(m)), 2),
        },
    )


def test_refs_spectrogram_and_k_power():
    import refs

    x = kick_loop(16).astype("float64")
    spec = refs.spectrogram(x, RATE)
    assert_golden(
        "refs-measures",
        {
            "frames": spec.shape[0],
            "bands": spec.shape[1],
            "mean": r(spec.mean(0), 1),
            "kBars": refs.kpower(x, RATE, 4 * BEAT),
            "packHead": refs.pack(spec)[:80],
        },
    )
