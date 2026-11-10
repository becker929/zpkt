"""The bring-your-own corpus: built from a folder, read back, and a render placed in it. Offline, no model."""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from ears import corpus
from ears.cli import app
from ears.models import AudioProfile, LoudnessFeatures, SpectralFeatures

SR = 48000


def tone(path, freq: float, amp: float, seconds: float = 2.0) -> None:
    t = np.arange(int(SR * seconds)) / SR
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.stack([x, x], axis=1), SR)


def profile(lufs: float, centroid: float, embedding=None) -> AudioProfile:
    return AudioProfile(loudness=LoudnessFeatures(lufs_integrated=lufs, true_peak_db=-1.0, band_energy={"sub": 0.5}),
                        spectral=SpectralFeatures(spectral_centroid_mean=centroid), embedding=embedding)


def fake_corpus(profiles: list[AudioProfile]) -> dict:
    tracks = [{"path": f"t{i}.wav", "seconds": 1.0, "features": corpus.features(p), "embedding": p.embedding}
              for i, p in enumerate(profiles)]
    return {"version": corpus.VERSION, "built_at": 0.0, "root": "", "tracks": tracks, "skipped": [],
            "stats": corpus._stats(tracks)}


def test_distance_places_each_measure_in_the_corpus() -> None:
    c = fake_corpus([profile(-10.0 + i, 1000.0 + 100 * i) for i in range(11)])   # LUFS -10..0, median -5
    inside = corpus.distance(profile(-5.0, 1500.0), c)["measures"]
    assert inside["lufs_integrated"]["z"] == pytest.approx(0.0)
    assert inside["lufs_integrated"]["median"] == pytest.approx(-5.0)
    assert inside["lufs_integrated"]["inside"]
    outside = corpus.distance(profile(-20.0, 1500.0), c)["measures"]["lufs_integrated"]
    assert outside["z"] < -3 and not outside["inside"]
    # a measure the corpus does not vary in has no z, rather than a division by zero
    assert corpus.distance(profile(-5.0, 1500.0), c)["measures"]["true_peak_db"]["z"] is None


def test_embedding_distance_needs_vectors_on_both_sides() -> None:
    a, b = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    c = fake_corpus([profile(-8.0, 1000.0, a), profile(-8.0, 1000.0, a), profile(-8.0, 1000.0, b)])
    near = corpus.distance(profile(-8.0, 1000.0, a), c)["embedding"]
    assert near["nearest"][0]["cosine"] == pytest.approx(1.0)
    assert near["nearest"][-1]["path"] == "t2.wav"
    assert near["to_centre"] > corpus.distance(profile(-8.0, 1000.0, b), c)["embedding"]["to_centre"]
    assert corpus.distance(profile(-8.0, 1000.0), c)["embedding"] is None
    assert corpus.distance(profile(-8.0, 1000.0, a), fake_corpus([profile(-8.0, 1000.0)]))["embedding"] is None


def test_build_and_distance_through_the_cli(tmp_path) -> None:
    refs = tmp_path / "refs"
    (refs / "sub").mkdir(parents=True)
    tone(refs / "a.wav", 110, 0.5)
    tone(refs / "sub" / "b.wav", 220, 0.25)
    (refs / "notes.txt").write_text("not audio")
    out = tmp_path / "corpus.json"
    runner = CliRunner()
    built = runner.invoke(app, ["corpus", "build", str(refs), "--out", str(out), "--no-embeddings"])
    assert built.exit_code == 0, built.output
    saved = json.loads(out.read_text())
    assert sorted(t["path"] for t in saved["tracks"]) == ["a.wav", "sub/b.wav"]
    assert saved["stats"]["lufs_integrated"]["n"] == 2

    mine = tmp_path / "mine.wav"
    tone(mine, 110, 0.5)
    res = runner.invoke(app, ["corpus", "distance", str(mine), "--corpus", str(out), "--no-embeddings", "--json"])
    assert res.exit_code == 0, res.output
    result = json.loads(res.output)
    assert result["corpus_tracks"] == 2 and result["embedding"] is None
    a = next(t for t in saved["tracks"] if t["path"] == "a.wav")
    assert result["measures"]["lufs_integrated"]["value"] == pytest.approx(a["features"]["lufs_integrated"], abs=0.01)


def test_missing_corpus_and_empty_folder_say_what_to_do(tmp_path) -> None:
    runner = CliRunner()
    wav = tmp_path / "x.wav"
    tone(wav, 110, 0.5)
    res = runner.invoke(app, ["corpus", "distance", str(wav), "--corpus", str(tmp_path / "none.json")])
    assert res.exit_code == 1 and "ears corpus build" in " ".join(res.output.split())
    (tmp_path / "empty").mkdir()
    res = runner.invoke(app, ["corpus", "build", str(tmp_path / "empty"), "--out", str(tmp_path / "c.json")])
    assert res.exit_code == 1 and "no audio files" in " ".join(res.output.split())
