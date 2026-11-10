"""Structural/audio-integrity sanity check for bounced multitrack stems.

Stdlib only (wave + array), chunked so multi-hundred-MB wavs don't need to
fully load into memory. For every *.wav next to a *.params.json in the given
directories it reports:

  - duration, sample rate, channels, bit depth
  - overall peak dBFS
  - a per-second peak profile used to flag two structural problems:
      * a MID-FILE DROPOUT: a stretch of near-digital-silence surrounded by
        louder audio on both sides (the "arrangement playback rendered
        silent" failure mode HANDOFF.md warns about, if it hit mid-take
        instead of the whole take).
      * HARD CLIPPING: many samples pinned at full-scale.

Usage:
    uv run python sweeps/check_stems.py sweeps/out/live_multitrack_bounce_v1/snts-style-track \\
                                          sweeps/out/live_multitrack_bounce_v1/hw002
"""
from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path

SILENCE_DBFS = -60.0       # below this, a 1s window counts as "silent"
LOUD_DBFS = -40.0          # above this, a 1s window counts as "has content"
MIN_DROPOUT_S = 2.0        # minimum silent stretch (surrounded by loud audio) to flag


def per_second_peaks(path: Path) -> tuple[list[float], int, int, int, int]:
    """Return (peak_dbfs_per_1s_window, sample_rate, channels, sampwidth, n_frames)."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        width = wf.getsampwidth()
        n_frames = wf.getnframes()
        frames_per_window = sr  # 1 second
        peaks: list[float] = []
        full_scale = float(1 << (8 * width - 1))
        fmt = "h" if width == 2 else ("i" if width == 4 else None)
        while True:
            raw = wf.readframes(frames_per_window)
            if not raw:
                break
            if fmt is not None:
                usable = len(raw) - (len(raw) % width)
                samples = array.array(fmt)
                samples.frombytes(raw[:usable])
                peak = max((abs(s) for s in samples), default=0) / full_scale
            elif width == 3:
                worst = 0
                for off in range(0, len(raw) - 2, 3):
                    v = abs(int.from_bytes(raw[off:off + 3], "little", signed=True))
                    worst = max(worst, v)
                peak = worst / full_scale
            else:
                peak = 0.0
            peaks.append(20.0 * math.log10(peak) if peak > 0 else -math.inf)
    return peaks, sr, ch, width, n_frames


def find_dropouts(peaks: list[float]) -> list[tuple[int, int]]:
    """Return (start_s, end_s) ranges of MID_DROPOUT_S+ silence flanked by loud audio."""
    n = len(peaks)
    silent = [p < SILENCE_DBFS for p in peaks]
    loud = [p > LOUD_DBFS for p in peaks]
    dropouts = []
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            run_len = j - i
            has_loud_before = any(loud[max(0, i - 3):i])
            has_loud_after = any(loud[j:j + 3])
            if run_len >= MIN_DROPOUT_S and has_loud_before and has_loud_after:
                dropouts.append((i, j))
            i = j
        else:
            i += 1
    return dropouts


def check_dir(d: Path) -> list[dict]:
    rows = []
    for wav_path in sorted(d.glob("*.wav")):
        sidecar = wav_path.with_suffix("").with_suffix(".params.json")
        peaks, sr, ch, width, n_frames = per_second_peaks(wav_path)
        duration = n_frames / sr if sr else 0.0
        overall_peak = max(peaks) if peaks else -math.inf
        dropouts = find_dropouts(peaks)
        clip_windows = sum(1 for p in peaks if p > -0.1)  # essentially 0 dBFS
        rows.append({
            "file": wav_path.name,
            "has_sidecar": sidecar.exists(),
            "duration_s": round(duration, 2),
            "sample_rate": sr,
            "channels": ch,
            "bit_depth": width * 8,
            "overall_peak_dbfs": None if overall_peak == -math.inf else round(overall_peak, 1),
            "dropouts": dropouts,
            "near_0dbfs_seconds": clip_windows,
        })
    return rows


def main() -> None:
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        print(__doc__)
        raise SystemExit(1)
    any_problem = False
    for d in dirs:
        print(f"\n=== {d} ===")
        rows = check_dir(d)
        durations = [r["duration_s"] for r in rows]
        srs = {r["sample_rate"] for r in rows}
        for r in rows:
            flags = []
            if not r["has_sidecar"]:
                flags.append("NO SIDECAR")
            if r["dropouts"]:
                flags.append(f"DROPOUT(S) at {r['dropouts']}s")
            if r["near_0dbfs_seconds"] >= 3:
                flags.append(f"POSSIBLE CLIPPING ({r['near_0dbfs_seconds']}s near 0 dBFS)")
            flag_str = ("  <-- " + "; ".join(flags)) if flags else ""
            if flags:
                any_problem = True
            print(f"  {r['file']:55s} {r['duration_s']:7.2f}s  {r['sample_rate']}Hz "
                  f"{r['bit_depth']}bit  peak {r['overall_peak_dbfs']:>6}dBFS{flag_str}")
        if len(srs) > 1:
            print(f"  ! MIXED SAMPLE RATES in this folder: {srs}")
            any_problem = True
        if durations:
            print(f"  duration range: {min(durations):.2f}s .. {max(durations):.2f}s "
                  f"(spread {max(durations) - min(durations):.2f}s)")
    print("\nRESULT:", "problems flagged above" if any_problem else "no structural issues found")


if __name__ == "__main__":
    main()
