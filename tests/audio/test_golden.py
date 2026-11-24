"""What ears reports on fixed synthetic audio, pinned (see golden_check.py): the profile, the corpus and the CLI.

Offline: no model (the embedding path runs on a stand-in for the ONNX session), no optional extractors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from ears.analyzer import analyze
from ears.cli import app
from ears.models import AudioProfile
from golden_check import check, plain, text
from typer.testing import CliRunner

from ears import corpus, embeddings, features, loudness

SR = 44100


def stereo(seconds: float = 3.0, seed: int = 1) -> np.ndarray:
    """A low tone and a high tone, panned apart, over a little noise: L and R differ."""
    t = np.arange(int(SR * seconds)) / SR
    rng = np.random.default_rng(seed)
    left = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.05 * rng.standard_normal(t.size)
    right = 0.2 * np.sin(2 * np.pi * 3000 * t) + 0.05 * rng.standard_normal(t.size)
    return np.stack([left, right], axis=1).astype(np.float32)


def write(path: Path, x: np.ndarray) -> Path:
    sf.write(path, x, SR, subtype="FLOAT")
    return path


def measured(profile: AudioProfile) -> dict:
    """The profile without what depends on where and when it was measured."""
    d = profile.to_dict()
    for key in ("clip_id", "audio_path", "extracted_at"):
        d.pop(key)
    return d


@pytest.fixture
def console_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rich prints plain text at a fixed width; files are named relative to tmp_path, so lines do not wrap."""
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.chdir(tmp_path)


def test_profile(tmp_path: Path) -> None:
    path = write(tmp_path / "take.wav", stereo())
    check("profile", measured(analyze(str(path), run_embeddings=False)))


def test_profile_mono_file_and_optional_extractors(tmp_path: Path) -> None:
    path = write(tmp_path / "mono.wav", stereo()[:, 0])
    p = analyze(str(path), run_embeddings=False, run_rhythm=True, run_pitch=True)
    check("profile_mono", {**measured(p), "errors": sorted(p.errors)})


def test_loudness_and_features() -> None:
    x = stereo(4.0, seed=2)
    mono = x.mean(axis=1)
    check(
        "loudness_features",
        {
            "extract": loudness.extract(mono, SR, x),
            "extract_mono_only": loudness.extract(mono, SR),
            "true_peak": loudness.true_peak_dbtp(x, SR),
            "true_peak_96k": loudness.true_peak_dbtp(x, 96000),
            "camelot": [loudness._to_camelot(k, s) for k, s in (("A", "minor"), ("F#", "major"), ("Cb", "major"))],
            "bands": loudness.BANDS,
            "spectral": features.extract(mono, SR),
        },
    )


def test_embedding_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The segmenting, mel and averaging around the model, with a stand-in session that sums mel rows."""

    class Session:
        def __init__(self, path: str, providers: list[str]) -> None:
            self.path = path

        def get_inputs(self) -> list:
            return [type("Input", (), {"name": "mel"})()]

        def run(self, outputs: None, feeds: dict) -> list:
            mel = feeds["mel"]
            assert mel.shape[:2] == (1, 1)
            return [mel[0, 0].mean(axis=1)[:16]]

    import onnxruntime

    model = tmp_path / "model.onnx"
    model.write_bytes(b"")
    monkeypatch.setenv("EARS_DCLAP_MODEL", str(model))
    monkeypatch.setattr(onnxruntime, "InferenceSession", Session)
    long = write(tmp_path / "long.wav", stereo(12.0))
    short = write(tmp_path / "short.wav", stereo(2.0))
    check(
        "embedding_pipeline",
        {
            "model_path": str(embeddings.model_path()) == str(model),
            "long": embeddings.embed(str(long)),
            "short": embeddings.embed(str(short)),
        },
    )
    monkeypatch.delenv("EARS_DCLAP_MODEL")
    assert embeddings.model_path() == Path("~/.cache/zpkt/models/dclap/model_epoch_36.onnx").expanduser()


def test_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refs = tmp_path / "refs"
    (refs / "deep").mkdir(parents=True)
    for i, name in enumerate(("a.wav", "deep/b.wav", "c.wav")):
        write(refs / name, stereo(2.0, seed=10 + i) * (0.5 + 0.25 * i))
    (refs / ".hidden.wav").write_bytes(b"")
    (refs / "broken.flac").write_bytes(b"not audio")
    built = corpus.build(refs, embeddings=False)
    rows = json.loads(
        json.dumps({k: v for k, v in built.items() if k not in ("built_at", "root")}).replace(str(refs), "<refs>")
    )
    vectors = [[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 0.6, 0.8]]
    for track, v in zip(built["tracks"], vectors, strict=True):
        track["embedding"] = v
    mine = analyze(str(write(tmp_path / "mine.wav", stereo(2.0, seed=20))), run_embeddings=False)
    mine.embedding = [0.9, 0.3, 0.1]
    monkeypatch.setenv("EARS_CORPUS", str(tmp_path / "c.json"))
    check(
        "corpus",
        {
            "built": rows,
            "files": [str(p.relative_to(refs)) for p in corpus.audio_files(refs)],
            "distance": corpus.distance(mine, built, nearest=2),
            "features": corpus.features(mine),
            "default_path": str(corpus.default_path()) == str(tmp_path / "c.json"),
        },
    )
    corpus.save({**built, "version": 0}, tmp_path / "old.json")
    with pytest.raises(ValueError, match="corpus version 0, this ears reads 1; rebuild it"):
        corpus.load(tmp_path / "old.json")


def test_cli_analyze(tmp_path: Path, console_env: None) -> None:
    path = write(tmp_path / "take.wav", stereo())
    res = CliRunner().invoke(app, ["analyze", str(path), "--no-embeddings"])
    assert res.exit_code == 0, res.output
    text("cli_analyze", re.sub(r"clip_id:   [0-9a-f]{16}", "clip_id:   <id>", res.output))
    res = CliRunner().invoke(app, ["analyze", str(path), "--no-embeddings", "--json"])
    out = json.loads(res.output)
    assert out["clip_id"] == analyze(str(path), run_embeddings=False).clip_id
    check("cli_analyze_json", {k: v for k, v in out.items() if k not in ("clip_id", "audio_path", "extracted_at")})
    res = CliRunner().invoke(app, ["analyze", str(tmp_path / "none.wav")])
    assert res.exit_code == 1 and "File not found" in res.output


def test_cli_compare(tmp_path: Path, console_env: None) -> None:
    write(tmp_path / "a.wav", stereo(seed=3))
    write(tmp_path / "b.wav", stereo(seed=4) * 0.5)
    res = CliRunner().invoke(app, ["compare", "a.wav", "b.wav", "--no-embeddings"])
    assert res.exit_code == 0, res.output
    text("cli_compare", res.output)


def test_cli_corpus(tmp_path: Path, console_env: None) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    for i in range(3):
        write(refs / f"r{i}.wav", stereo(2.0, seed=30 + i) * (0.4 + 0.2 * i))
    runner = CliRunner()
    res = runner.invoke(app, ["corpus", "build", "refs", "--out", "corpus.json", "--no-embeddings"])
    assert res.exit_code == 0, res.output
    text("cli_corpus_build", res.output)
    write(tmp_path / "mine.wav", stereo(2.0, seed=40))
    res = runner.invoke(app, ["corpus", "distance", "mine.wav", "--corpus", "corpus.json", "--no-embeddings"])
    assert res.exit_code == 0, res.output
    text("cli_corpus_distance", res.output)
    res = runner.invoke(app, ["corpus", "build", "nope", "--out", "corpus.json"])
    assert res.exit_code == 1 and "Not a folder" in res.output


def test_profile_dict_is_json() -> None:
    p = AudioProfile(clip_id="x", embedding=[np.float32(0.5)])
    assert json.dumps(plain(p.to_dict()))


def test_print_profile_every_section(capsys: pytest.CaptureFixture[str], console_env: None) -> None:
    """The sections the synthetic files never fill: key, danceability, rhythm, embedding, errors."""
    from ears.cli import _print_profile
    from ears.models import LoudnessFeatures, RhythmFeatures, SpectralFeatures

    profile = AudioProfile(
        clip_id="abc",
        duration_seconds=1.5,
        sample_rate=48000,
        loudness=LoudnessFeatures(lufs_integrated=-9.5, true_peak_db=-0.3, camelot_key="8A", band_energy={"sub": 0.5}),
        spectral=SpectralFeatures(spectral_centroid_mean=1234.5, key="A minor", key_strength=0.8, danceability=1.25),
        rhythm=RhythmFeatures(bpm=160.0, meter_numerator=4, swing_ratio=0.52),
        embedding=[0.1, 0.2, 0.3, 0.4, 0.5],
        errors=["one failed: why", "two failed: why"],
    )
    _print_profile("x.wav", profile)
    _print_profile("y.wav", AudioProfile(rhythm=RhythmFeatures()))
    text("print_profile", capsys.readouterr().out)
