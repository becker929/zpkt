"""A reference corpus: a folder of tracks you want yours to sit among, and how far a render is from it.

`build` measures every audio file in a folder once and writes one JSON file. `distance` places a render in
that corpus, one measure at a time: its value, where the corpus sits (median, 10th to 90th percentile) and
how many corpus standard deviations away it is. With the DCLAP model it also reports the embedding's
similarity to the corpus centre and the nearest tracks.

The corpus is yours: no audio or measurements ship with ears. Loudness, peak and spectra need no corpus.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .models import AudioProfile

VERSION = 1
AUDIO = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg"}
DEFAULT_PATH = "~/.cache/zpkt/corpus.json"


def default_path() -> Path:
    """$EARS_CORPUS, else ~/.cache/zpkt/corpus.json."""
    return Path(os.environ.get("EARS_CORPUS") or DEFAULT_PATH).expanduser()


def features(profile: AudioProfile) -> dict[str, float]:
    """The scalar measures a corpus keeps per track, by name. A measure the profile lacks is left out."""
    out: dict[str, float | None] = {}
    if profile.loudness:
        ld = profile.loudness
        out["lufs_integrated"] = ld.lufs_integrated
        out["true_peak_db"] = ld.true_peak_db
        for band, share in ld.band_energy.items():
            out[f"band_{band}"] = share
    if profile.spectral:
        sp = profile.spectral
        out["spectral_centroid_hz"] = sp.spectral_centroid_mean
        out["spectral_rolloff_hz"] = sp.spectral_rolloff_mean
        out["spectral_bandwidth_hz"] = sp.spectral_bandwidth_mean
        out["spectral_flatness"] = sp.spectral_flatness_mean
        out["onset_strength"] = sp.onset_strength_mean
    return {k: float(v) for k, v in out.items() if v is not None and np.isfinite(v)}


def audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO and not p.name.startswith("."))


def build(folder: Path, *, embeddings: bool = True, analyze: Callable[..., AudioProfile] | None = None,
          progress: Callable[[int, int, Path], None] | None = None) -> dict:
    """Measure every audio file under `folder` and return the corpus (see `save`). Files that fail to load are
    listed under "skipped" with the reason."""
    if analyze is None:
        from .analyzer import analyze
    folder = Path(folder).expanduser()
    files = audio_files(folder)
    if not files:
        raise ValueError(f"{folder}: no audio files ({', '.join(sorted(AUDIO))})")
    tracks, skipped = [], []
    for i, path in enumerate(files):
        if progress:
            progress(i, len(files), path)
        profile = analyze(str(path), run_embeddings=embeddings)
        feats = features(profile)
        if not feats:
            skipped.append({"path": str(path.relative_to(folder)), "why": "; ".join(profile.errors) or "no measures"})
            continue
        tracks.append({"path": str(path.relative_to(folder)), "seconds": round(profile.duration_seconds, 2),
                       "features": feats, "embedding": profile.embedding})
    if not tracks:
        raise ValueError(f"{folder}: none of the {len(files)} files could be measured")
    return {"version": VERSION, "built_at": time.time(), "root": str(folder), "tracks": tracks,
            "skipped": skipped, "stats": _stats(tracks)}


def _stats(tracks: Iterable[dict]) -> dict[str, dict[str, float]]:
    columns: dict[str, list[float]] = {}
    for track in tracks:
        for name, value in track["features"].items():
            columns.setdefault(name, []).append(value)
    stats = {}
    for name, values in columns.items():
        v = np.asarray(values, dtype=float)
        p10, p50, p90 = np.percentile(v, [10, 50, 90])
        stats[name] = {"n": len(v), "mean": float(v.mean()), "std": float(v.std()),
                       "p10": float(p10), "median": float(p50), "p90": float(p90)}
    return stats


def save(corpus: dict, path: Path) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corpus))
    return path


def load(path: Path | None = None) -> dict:
    path = Path(path).expanduser() if path else default_path()
    if not path.is_file():
        raise FileNotFoundError(f"no corpus at {path}: build one with `ears corpus build FOLDER`")
    corpus = json.loads(path.read_text())
    if corpus.get("version") != VERSION:
        raise ValueError(f"{path}: corpus version {corpus.get('version')!r}, this ears reads {VERSION}; rebuild it")
    return corpus


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / (np.linalg.norm(vectors, axis=-1, keepdims=True) + 1e-12)


def distance(profile: AudioProfile, corpus: dict, *, nearest: int = 3) -> dict:
    """Where `profile` sits in `corpus`.

    "measures": per measure, the render's value, the corpus median, p10 and p90, z (corpus standard deviations
    from the corpus mean; None when the corpus does not vary) and inside (within p10..p90).
    "embedding": None without embeddings on both sides, else the cosine similarity to the corpus centre, the
    same similarity for the corpus's own tracks (median, p10) and the nearest tracks.
    """
    measures = {}
    for name, value in features(profile).items():
        s = corpus["stats"].get(name)
        if not s:
            continue
        measures[name] = {"value": value, "median": s["median"], "p10": s["p10"], "p90": s["p90"],
                          "z": (value - s["mean"]) / s["std"] if s["std"] > 0 else None,
                          "inside": s["p10"] <= value <= s["p90"]}
    embedding = None
    with_vectors = [t for t in corpus["tracks"] if t.get("embedding")]
    if profile.embedding and with_vectors and len(with_vectors[0]["embedding"]) == len(profile.embedding):
        vectors = _unit(np.asarray([t["embedding"] for t in with_vectors], dtype=float))
        centre = _unit(vectors.mean(axis=0))
        mine = _unit(np.asarray(profile.embedding, dtype=float))
        own = vectors @ centre
        sims = vectors @ mine
        order = np.argsort(-sims)[:nearest]
        embedding = {"to_centre": float(mine @ centre), "corpus_median": float(np.median(own)),
                     "corpus_p10": float(np.percentile(own, 10)),
                     "nearest": [{"path": with_vectors[i]["path"], "cosine": float(sims[i])} for i in order]}
    return {"corpus_tracks": len(corpus["tracks"]), "measures": measures, "embedding": embedding}
