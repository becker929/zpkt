"""Bulk corpus annotation tool.

Extracts short clips from a directory of audio files, analyzes them,
and drives an interactive annotation review.

Clip sampling:
  - Duration: non-uniform, 5–25s (beta-distributed, peak ~10s)
  - Position: uniform random across the "body" of the track (skip first/last 30s)
  - N clips per track: configurable (default 3)
  - Saved as WAV in --clips-dir (default: ./clips/)

Phases:
  --clip      Extract clips from source directory into clips-dir
  --analyze   Analyze all clips in clips-dir and cache profiles
  --review    Interactive annotation of cached clips

Default (no flags): run all three phases sequentially.

Examples:
    uv run python bulk_annotate.py <dir>                    # full pipeline
    uv run python bulk_annotate.py <dir> --clip             # just extract clips
    uv run python bulk_annotate.py <dir> --analyze          # analyze existing clips
    uv run python bulk_annotate.py <dir> --review           # annotate cached clips
    uv run python bulk_annotate.py <dir> --n-clips 5        # 5 clips per track
    uv run python bulk_annotate.py <dir> --clips-dir /tmp/c # custom clip output dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg"}

# Non-uniform clip duration: beta(2,4) scaled to [5,25] peaks around 9–11s
def _sample_duration(rng: random.Random) -> float:
    return 5.0 + 20.0 * rng.betavariate(2, 4)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk clip → analyze → annotate audio corpus builder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", help="Source directory of audio files.")
    parser.add_argument("--clip", action="store_true", help="Extract clips only.")
    parser.add_argument("--analyze", action="store_true", help="Analyze clips only.")
    parser.add_argument("--review", action="store_true", help="Annotation review only.")
    parser.add_argument(
        "--clips-dir", default="./clips",
        help="Directory to store extracted clips (default: ./clips).",
    )
    parser.add_argument(
        "--n-clips", type=int, default=3,
        help="Clips to extract per track (default: 3).",
    )
    parser.add_argument(
        "--min-dur", type=float, default=5.0,
        help="Minimum clip duration in seconds (default: 5).",
    )
    parser.add_argument(
        "--max-dur", type=float, default=25.0,
        help="Maximum clip duration in seconds (default: 25).",
    )
    parser.add_argument(
        "--body-skip", type=float, default=30.0,
        help="Seconds to skip at start/end of each track (default: 30).",
    )
    parser.add_argument(
        "--workers", type=int, default=2,
        help="Parallel workers for analysis (default: 2).",
    )
    parser.add_argument(
        "--no-judge", action="store_true",
        help="Skip model prediction in review (faster).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for clip sampling (default: 42).",
    )
    args = parser.parse_args()

    audio_dir = Path(args.directory)
    clips_dir = Path(args.clips_dir)

    if not audio_dir.exists():
        print(f"ERROR: directory not found: {audio_dir}")
        sys.exit(1)

    run_all = not (args.clip or args.analyze or args.review)

    if args.clip or run_all:
        extract_clips(
            audio_dir, clips_dir,
            n_clips=args.n_clips,
            min_dur=args.min_dur,
            max_dur=args.max_dur,
            body_skip=args.body_skip,
            seed=args.seed,
        )

    if args.analyze or run_all:
        batch_analyze(clips_dir, workers=args.workers)

    if args.review or run_all:
        interactive_review(clips_dir, skip_judge=args.no_judge)


# ── Phase 1: Clip extraction ──────────────────────────────────────────────────

def extract_clips(
    audio_dir: Path,
    clips_dir: Path,
    n_clips: int = 3,
    min_dur: float = 5.0,
    max_dur: float = 25.0,
    body_skip: float = 30.0,
    seed: int = 42,
) -> list[Path]:
    """Slice each track into N random clips and save as WAV."""
    import soundfile as sf
    import librosa

    clips_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    tracks = _unique_tracks(audio_dir)
    print(f"\n{'='*60}")
    print(f"  Clip Extraction — {len(tracks)} tracks → ~{len(tracks) * n_clips} clips")
    print(f"  Duration: {min_dur:.0f}–{max_dur:.0f}s (non-uniform)  |  Skip: {body_skip:.0f}s head/tail")
    print(f"  Output: {clips_dir}")
    print(f"{'='*60}\n")

    all_clips: list[Path] = []
    skipped = 0

    for i, track in enumerate(tracks):
        try:
            # Get duration without loading entire file
            info = sf.info(str(track))
            total_dur = info.duration
        except Exception:
            try:
                # Fallback for MP3 / formats soundfile can't probe
                total_dur = librosa.get_duration(path=str(track))
            except Exception as e:
                print(f"  [{i+1:>3}/{len(tracks)}] SKIP (probe failed) {track.name}: {e}")
                skipped += 1
                continue

        body_start = body_skip
        body_end = total_dur - body_skip

        if body_end - body_start < min_dur:
            # Track too short for body skip — sample from full track
            body_start = 0.0
            body_end = total_dur

        if body_end - body_start < min_dur:
            print(f"  [{i+1:>3}/{len(tracks)}] SKIP (too short: {total_dur:.1f}s) {track.name}")
            skipped += 1
            continue

        clips_this_track = []
        attempts = 0
        while len(clips_this_track) < n_clips and attempts < n_clips * 4:
            attempts += 1
            dur = min(_sample_duration(rng), max_dur, body_end - body_start)
            dur = max(dur, min_dur)
            max_start = body_end - dur
            if max_start <= body_start:
                start = body_start
            else:
                start = rng.uniform(body_start, max_start)

            # Deduplicate: reject if within 5s of an already-chosen start
            if any(abs(start - s) < 5.0 for s in clips_this_track):
                continue

            clip_name = f"{track.stem}__{start:.0f}s_{dur:.0f}s.wav"
            clip_path = clips_dir / clip_name

            if clip_path.exists():
                clips_this_track.append(start)
                all_clips.append(clip_path)
                continue

            try:
                _write_clip(track, clip_path, start, dur)
                clips_this_track.append(start)
                all_clips.append(clip_path)
            except Exception as e:
                print(f"    clip write failed ({start:.0f}s): {e}")

        dur_str = f"{total_dur:.0f}s total"
        print(
            f"  [{i+1:>3}/{len(tracks)}] {track.name[:52]:<54} "
            f"{dur_str:>10}  → {len(clips_this_track)} clips"
        )

    print(f"\n  Extracted {len(all_clips)} clips from {len(tracks) - skipped} tracks "
          f"({skipped} skipped) into {clips_dir}\n")
    return all_clips


def _write_clip(source: Path, dest: Path, start_sec: float, dur_sec: float) -> None:
    """Extract a WAV clip using soundfile (fast, no re-encoding)."""
    import soundfile as sf
    import numpy as np

    try:
        info = sf.info(str(source))
        sr = info.samplerate
        start_frame = int(start_sec * sr)
        end_frame = int((start_sec + dur_sec) * sr)
        with sf.SoundFile(str(source)) as f:
            f.seek(start_frame)
            audio = f.read(end_frame - start_frame, dtype="float32", always_2d=False)
        sf.write(str(dest), audio, sr, subtype="PCM_16")
    except Exception:
        # Fallback for MP3 via librosa
        import librosa
        audio, sr = librosa.load(str(source), sr=None, mono=True,
                                 offset=start_sec, duration=dur_sec)
        import soundfile as sf
        sf.write(str(dest), audio, sr, subtype="PCM_16")


# ── Phase 2: Batch analysis ───────────────────────────────────────────────────

def batch_analyze(clips_dir: Path, workers: int = 2) -> None:
    from taste.corpus.store import CorpusStore
    from taste.audio.analyzer import analyze

    store = CorpusStore()
    clips = sorted(p for p in clips_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)

    # Skip already-cached clips
    pending = [c for c in clips if not store.get_cached_profile(_clip_id(str(c)))]

    print(f"\n{'='*60}")
    print(f"  Batch Analysis — {len(pending)} clips to analyze ({len(clips) - len(pending)} cached)")
    print(f"  Workers: {workers}  |  Clips dir: {clips_dir.name}")
    print(f"{'='*60}\n")

    if not pending:
        print("  All clips already cached. Run --review to annotate.\n")
        return

    def _analyze_one(path: Path):
        try:
            profile = analyze(str(path), run_pitch=False, run_stems=False)
            return path, profile, None
        except Exception as exc:
            return path, None, str(exc)

    done = 0
    errors = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyze_one, p): p for p in pending}
        for future in as_completed(futures):
            path, profile, err = future.result()
            done += 1
            elapsed = time.time() - t0
            eta = (elapsed / done) * (len(pending) - done) if done else 0

            if err is None:
                import dataclasses
                store.cache_profile(
                    profile.clip_id,
                    json.dumps(dataclasses.asdict(profile), default=str),
                )
                r = profile.rhythm
                lo = profile.loudness
                bpm_str = f"{r.bpm:.0f}bpm" if r and r.bpm else "?bpm"
                lufs_str = f"{lo.lufs_integrated:.1f}" if lo and lo.lufs_integrated else "?"
                key_str = lo.camelot_key if lo and lo.camelot_key else "?"
                print(
                    f"  [{done:>3}/{len(pending)}] {path.name[:50]:<52} "
                    f"{bpm_str:>8}  {lufs_str:>6} LUFS  {key_str:<5}  ETA {eta:.0f}s"
                )
            else:
                errors.append((path.name, err))
                print(f"  [{done:>3}/{len(pending)}] ERROR {path.name}: {err[:60]}")

    total_elapsed = time.time() - t0
    print(f"\n  Done: {done - len(errors)}/{len(pending)} in {total_elapsed:.0f}s")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for name, err in errors:
            print(f"    {name}: {err}")


# ── Phase 3: Interactive review ───────────────────────────────────────────────

def interactive_review(clips_dir: Path, skip_judge: bool = False) -> None:
    from taste.corpus.store import CorpusStore
    from taste.judge.taste_model import TasteModel
    from taste.corpus.models import AnnotationEntry, EvaluationLens

    store = CorpusStore()
    model = TasteModel(store=store) if not skip_judge else None

    clips = sorted(p for p in clips_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)

    # Match clips → cached profiles, exclude already-annotated
    all_annotated = {e.clip_id for e in store.get_all_annotations()}
    pending = []
    for c in clips:
        cid = _clip_id(str(c))
        raw = store.get_cached_profile(cid)
        if raw and cid not in all_annotated:
            pending.append((c, json.loads(raw)))

    corpus_size = store.stats()["total"]
    print(f"\n{'='*60}")
    print(f"  Interactive Annotation Review")
    print(f"  Corpus: {corpus_size} entries  |  Pending: {len(pending)} clips")
    print(f"{'='*60}")
    print("  1–5 = verdict   Enter = skip   n = notes   q = quit\n")

    if not pending:
        print("  Nothing to review. Run --analyze first.\n")
        return

    annotated = 0
    skipped = 0

    for i, (clip_path, data) in enumerate(pending):
        clip_id = data.get("clip_id", "")
        duration = data.get("duration_seconds", 0.0)
        embedding = data.get("embedding", [])

        print(f"{'─'*60}")
        print(f"  [{i+1}/{len(pending)}]  {clip_path.name}")
        _print_summary(data)

        # Model prediction
        predicted = None
        if model and embedding:
            try:
                from taste.audio.analyzer import AudioProfile
                p = AudioProfile()
                p.clip_id = clip_id
                p.audio_path = str(clip_path)
                p.duration_seconds = duration
                p.embedding = embedding
                p.description = data.get("description", "")
                v = model.judge(p)
                predicted = v.score
                ci = "▲" if v.confidence >= 0.7 else "~" if v.confidence >= 0.5 else "?"
                print(f"  Model: {predicted}/5 {ci}  ({v.confidence:.0%} conf)")
            except Exception as e:
                print(f"  Model prediction failed: {e}")

        works = ""
        fails = ""
        anchors = ""

        while True:
            try:
                raw = input("  Verdict [1–5 / Enter=skip / n=notes / q=quit]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Interrupted.")
                _print_session_summary(annotated, skipped, len(pending))
                return

            if raw == "q":
                _print_session_summary(annotated, skipped, len(pending))
                return
            if raw == "":
                skipped += 1
                break
            if raw == "n":
                works = input("  What works? ").strip()
                fails = input("  What fails? ").strip()
                anchors = input("  Anchors (optional): ").strip()
                continue
            try:
                v_int = int(raw)
                if not 1 <= v_int <= 5:
                    raise ValueError
                if not works:
                    works = input("  What works? (optional) ").strip()
                if not fails:
                    fails = input("  What fails? (optional) ").strip()

                entry = AnnotationEntry(
                    clip_id=clip_id,
                    source_track=clip_path.name,
                    time_range=(0.0, duration),
                    decomposition="full_mix",
                    evaluation_lens=EvaluationLens.overall,
                    verdict=v_int,
                    what_works=works,
                    what_fails=fails,
                    comparison_anchors=anchors,
                    embedding=embedding,
                )
                import dataclasses
                store.cache_profile(
                    clip_id,
                    json.dumps(dataclasses.asdict(
                        _dict_to_profile(data)
                    ), default=str),
                )
                row_id = store.add_annotation(entry)
                annotated += 1
                agree = "✓" if predicted == v_int else (
                    f"model said {predicted}" if predicted else ""
                )
                print(f"  Added #{row_id}  {agree}\n")
                break
            except ValueError:
                print("  Enter 1–5, Enter to skip, or q.")

    _print_session_summary(annotated, skipped, len(pending))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unique_tracks(audio_dir: Path) -> list[Path]:
    tracks = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    seen: set[str] = set()
    unique = []
    for t in tracks:
        stem = t.stem.replace(" copy", "").strip()
        if stem not in seen:
            seen.add(stem)
            unique.append(t)
    return unique


def _clip_id(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.abspath(path)}:{stat.st_mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _print_summary(data: dict) -> None:
    r = data.get("rhythm") or {}
    lo = data.get("loudness") or {}
    sp = data.get("spectral") or {}
    band = lo.get("band_energy") or {}

    parts = []
    if bpm := r.get("bpm"):
        parts.append(f"{bpm:.0f} BPM")
    if lufs := lo.get("lufs_integrated"):
        parts.append(f"{lufs:.1f} LUFS")
    if key := lo.get("camelot_key"):
        parts.append(f"key {key}")
    if dur := data.get("duration_seconds"):
        parts.append(f"{dur:.1f}s")
    if swing := r.get("swing_ratio"):
        parts.append(f"swing {swing:.2f}")
    print("  " + "  |  ".join(parts))

    if band:
        dom = max(band, key=band.get)
        print(
            f"  sub={band.get('sub',0):.0%}  low={band.get('low',0):.0%}  "
            f"mid={band.get('mid',0):.0%}  high={band.get('high',0):.0%}  "
            f"air={band.get('air',0):.0%}  (dominant: {dom})"
        )
    if c := sp.get("spectral_centroid_mean"):
        line = f"  centroid {c:.0f} Hz"
        if d := sp.get("danceability"):
            line += f"  |  danceability {d:.2f}"
        if gr := r.get("groove_density"):
            line += f"  |  groove {gr:.1f} onsets/beat"
        print(line)


def _dict_to_profile(data: dict):
    """Reconstruct minimal AudioProfile from cached dict (for cache re-write)."""
    from taste.audio.analyzer import AudioProfile
    p = AudioProfile()
    p.clip_id = data.get("clip_id", "")
    p.audio_path = data.get("audio_path", "")
    p.duration_seconds = data.get("duration_seconds", 0.0)
    p.description = data.get("description", "")
    p.embedding = data.get("embedding", [])
    return p


def _print_session_summary(annotated: int, skipped: int, total: int) -> None:
    print(f"\n{'─'*60}")
    print(f"  Session: {annotated} annotated  |  {skipped} skipped  |  {total} total")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
