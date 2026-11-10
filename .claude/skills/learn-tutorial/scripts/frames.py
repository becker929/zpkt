"""Pick the frames worth reading from a tutorial video: scene changes plus a periodic sample,
near-duplicates dropped, and contact sheets for a first look.

    run frames.py src/<id>.mp4 frames --scene 0.03 --every 2.5 --sheets

- Scene threshold: 0.03 for a DAW screencast (run 1's whole video never scored above 0.156, so
  0.2-0.3 found nothing); 0.2-0.3 for camera video.
- Periodic sample every --every s, because a screencast changes in small places.
- Dedupe: 160x90 grey thumbnails compared in 10x10-pixel blocks; a frame is dropped when no block
  changed by --block-thresh (0-255) from the last kept frame. A moved clip or a lit button is a
  local change and survives; a static repeat is dropped.
- --sheets: 4x3 contact sheets (frames/sheets/sheet_NN.jpg + sheets.json mapping cells to frames).
  Read the sheets first, then open single frames, then crop.py for small text.
Kept frames: OUTDIR/fNNN_tSSS.ss.jpg (<= 1280 px wide) and OUTDIR/frames.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

TW, TH, BS = 160, 90, 10
THUMB_FPS = 4.0


def probe_duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def scene_times(video: Path, thresh: float) -> list[tuple[float, float]]:
    cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-i", str(video), "-an", "-vf",
           f"select='gt(scene,{thresh})',metadata=print:file=-", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    times, t = [], None
    for line in out.splitlines():
        if m := re.search(r"pts_time:([\d.]+)", line):
            t = float(m.group(1))
        if (m := re.search(r"lavfi\.scene_score=([\d.]+)", line)) and t is not None:
            times.append((t, float(m.group(1))))
    return times


def thumbs(video: Path) -> np.ndarray:
    """Grey TWxTH thumbnails at THUMB_FPS: (n, TH, TW) uint8."""
    cmd = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(video), "-an",
           "-vf", f"fps={THUMB_FPS},scale={TW}:{TH}:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8)[: len(raw) // (TW * TH) * TW * TH].reshape(-1, TH, TW)


def max_block_diff(a: np.ndarray, b: np.ndarray) -> float:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).reshape(TH // BS, BS, TW // BS, BS)
    return float(d.mean(axis=(1, 3)).max())


def sheets(outdir: Path, files: list[str], cols: int = 4, rows: int = 3) -> list[dict]:
    sd = outdir / "sheets"
    sd.mkdir(exist_ok=True)
    per = cols * rows
    index = []
    for s in range(0, len(files), per):
        group = files[s:s + per]
        lst = sd / f"sheet_{s // per:02d}.txt"
        lst.write_text("".join(f"file '{(outdir / f).resolve()}'\nduration 1\n" for f in group))
        out = sd / f"sheet_{s // per:02d}.jpg"
        subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe",
                        "0", "-i", str(lst), "-vf", f"scale=640:-2,tile={cols}x{rows}:padding=4:color=white",
                        "-frames:v", "1", "-q:v", "3", str(out)], check=True)
        lst.unlink()
        index.append({"sheet": out.name, "cells_row_major": group})
    (sd / "sheets.json").write_text(json.dumps(index, indent=1) + "\n")
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--scene", type=float, default=0.03, help="scene-change threshold (screencast 0.03)")
    ap.add_argument("--every", type=float, default=2.5, help="periodic sample, s")
    ap.add_argument("--block-thresh", type=float, default=4.0, help="max block change to call a frame a repeat")
    ap.add_argument("--sheets", action="store_true", help="also make 4x3 contact sheets")
    a = ap.parse_args()

    video, outdir = Path(a.video), Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)
    th = thumbs(video)
    last = len(th) - 1
    cands: dict[int, dict] = {}
    scenes = scene_times(video, a.scene)
    for t, s in scenes:  # take the frame ~0.4 s after a cut, when zooms and fades have settled
        tt = min(duration - 0.05, t + 0.4)
        cands[min(last, int(round(tt * THUMB_FPS)))] = {"t": round(tt, 2), "reason": "scene", "scene_score": round(s, 3)}
    t = 0.5
    while t < duration:
        cands.setdefault(min(last, int(round(t * THUMB_FPS))),
                         {"t": round(t, 2), "reason": f"every {a.every:g} s", "scene_score": None})
        t += a.every

    kept: list[tuple[int, dict]] = []
    dropped = 0
    for i in sorted(cands):
        c = cands[i]
        if kept:
            c["diff_prev_maxblock"] = round(max_block_diff(th[kept[-1][0]], th[i]), 2)
            if c["diff_prev_maxblock"] < a.block_thresh:
                dropped += 1
                continue
        kept.append((i, c))
    for n, (_, c) in enumerate(kept):
        c["file"] = f"f{n:03d}_t{c['t']:06.2f}.jpg"
        subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss",
                        f"{c['t']:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v",
                        "2", str(outdir / c["file"])], check=True)
    meta = {"video": video.name, "scene_threshold": a.scene, "every_s": a.every, "block_thresh": a.block_thresh,
            "scene_cuts": len(scenes), "max_scene_score": max((s for _, s in scenes), default=None),
            "candidates": len(cands), "dropped_near_dupes": dropped, "kept": [c for _, c in kept]}
    (outdir / "frames.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"scene cuts {len(scenes)} (max score {meta['max_scene_score']}), candidates {len(cands)}, "
          f"dropped {dropped}, kept {len(kept)} -> {outdir}")
    if a.sheets:
        idx = sheets(outdir, [c["file"] for _, c in kept])
        print(f"{len(idx)} contact sheets -> {outdir / 'sheets'}")


if __name__ == "__main__":
    main()
