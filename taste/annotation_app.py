"""
Annotation web app — serves clips and saves verdicts to taste_corpus.db.

    uv run python annotation_app.py
    uv run python annotation_app.py --clips-dir ./clips --port 5001
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg"}

app = Flask(__name__)
_clips_dir: Path = Path("./clips")


# ── Audio serving ─────────────────────────────────────────────────────────────

@app.route("/audio/<path:filename>")
def serve_audio(filename: str):
    # send_from_directory refuses paths that escape the clips folder. Joining
    # the URL path directly let /audio/..%2f..%2fetc%2fhosts read any file.
    if not (_clips_dir / filename).resolve().is_relative_to(_clips_dir.resolve()):
        abort(404)
    return send_from_directory(_clips_dir.resolve(), filename, mimetype=_mime(Path(filename).suffix))


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("annotate.html")


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/clips")
def api_clips():
    """Return all pending (cached, not yet annotated) clips."""
    store = _store()

    # Single pass: load everything from DB at once
    annotated_ids = {e.clip_id for e in store.get_all_annotations()}
    all_profiles = _load_all_profiles(store)   # {clip_id: parsed_dict}

    # Build clip_id → path map from filesystem (one stat per file)
    path_map: dict[str, Path] = {}
    for p in _clips_dir.iterdir():
        if p.suffix.lower() not in AUDIO_EXTS:
            continue
        cid = _clip_id(str(p))
        path_map[cid] = p

    clips = []
    for cid, p in sorted(path_map.items(), key=lambda kv: kv[1].name):
        if cid in annotated_ids:
            continue
        data = all_profiles.get(cid)
        if not data:
            continue
        clips.append(_clip_payload(p, cid, data))

    stats = store.stats()
    return jsonify({"clips": clips, "corpus_size": stats["total"], "total_clips": len(path_map)})


@app.route("/api/annotate", methods=["POST"])
def api_annotate():
    body = request.get_json(force=True)
    store = _store()

    cid = body["clip_id"]
    raw = store.get_cached_profile(cid)
    profile_data = json.loads(raw) if raw else {}

    from taste.corpus.models import AnnotationEntry, EvaluationLens
    entry = AnnotationEntry(
        clip_id=cid,
        source_track=body["filename"],
        time_range=(0.0, profile_data.get("duration_seconds", 0.0)),
        decomposition="full_mix",
        evaluation_lens=EvaluationLens.overall,
        verdict=int(body["verdict"]),
        what_works=body.get("works", ""),
        what_fails=body.get("fails", ""),
        comparison_anchors=body.get("anchors", ""),
        embedding=profile_data.get("embedding", []),
    )
    row_id = store.add_annotation(entry)
    return jsonify({"ok": True, "row_id": row_id})


@app.route("/api/stats")
def api_stats():
    return jsonify(_store().stats())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _store():
    from taste.corpus.store import CorpusStore
    return CorpusStore()


def _load_all_profiles(store) -> dict:
    """Bulk-load all cached profiles in one DB query → {clip_id: dict}."""
    import sqlite3
    profiles = {}
    try:
        with sqlite3.connect(str(store._db_path)) as conn:
            for row in conn.execute("SELECT clip_id, profile_json FROM audio_profiles"):
                try:
                    profiles[row[0]] = json.loads(row[1])
                except Exception:
                    pass
    except Exception:
        pass
    return profiles


def _clip_id(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.abspath(path)}:{stat.st_mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _mime(suffix: str) -> str:
    return {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac",
            "ogg": "audio/ogg"}.get(suffix.lstrip(".").lower(), "audio/wav")


def _clip_payload(path: Path, cid: str, data: dict) -> dict:
    r = data.get("rhythm") or {}
    lo = data.get("loudness") or {}
    sp = data.get("spectral") or {}
    band = lo.get("band_energy") or {}

    # Parse source track name from clip filename: track__Xs_Ys.wav
    stem = path.stem
    source = stem.split("__")[0] if "__" in stem else stem
    timing = stem.split("__")[1] if "__" in stem else ""

    return {
        "filename": path.name,
        "clip_id": cid,
        "source": source,
        "timing": timing,
        "duration": round(data.get("duration_seconds", 0), 1),
        "bpm": round(r["bpm"], 1) if r.get("bpm") else None,
        "lufs": round(lo["lufs_integrated"], 1) if lo.get("lufs_integrated") is not None else None,
        "key": lo.get("camelot_key"),
        "band": {k: round(v, 3) for k, v in band.items()} if band else {},
        "centroid": round(sp["spectral_centroid_mean"]) if sp.get("spectral_centroid_mean") else None,
        "danceability": round(sp["danceability"], 2) if sp.get("danceability") is not None else None,
        "swing": round(r["swing_ratio"], 2) if r.get("swing_ratio") else None,
        "groove": round(r["groove_density"], 1) if r.get("groove_density") else None,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Taste annotation web app.")
    parser.add_argument("--clips-dir", default="./clips")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    global _clips_dir
    _clips_dir = Path(args.clips_dir)
    if not _clips_dir.exists():
        print(f"ERROR: clips dir not found: {_clips_dir}")
        return

    print(f"\n  Scaling Taste — Annotation App")
    print(f"  Clips dir: {_clips_dir}  ({sum(1 for p in _clips_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)} clips)")
    print(f"  Open: http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
