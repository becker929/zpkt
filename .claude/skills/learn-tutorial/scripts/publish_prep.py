"""Prepare a /skrng batch from practice renders: MP3s with one common gain, spoken announcements,
and entries.json with the manifest entries, the batch and an upload map. Publishing is separate.

    run publish_prep.py prep practice/publish.json --out practice/publish        # always
    run publish_prep.py upload practice/publish/entries.json                      # prints the commands
    run publish_prep.py upload practice/publish/entries.json --yes                # only when permitted
    run publish_prep.py apply practice/publish/entries.json --site ~/_agent_scratch/site

publish.json (written by the practice agent):
  {"batch": 9, "date": "2026-10-11", "bpm": 123,
   "batch_title": "Batch 9 - Tutorial practice: ... (11 Oct)", "intro": "Tutorial practice: ...",
   "batch_notes": "...", "credit": {"title": "...", "channel": "...", "url": "https://..."},
   "tracks": [{"id": "2026-10-11-tut-x-a-faithful", "label": "faithful to the tutorial",
               "raw": "../renders/A_raw.wav", "notes": "..."}, ...]}
Paths are relative to publish.json.

prep: one gain for every track, so the batch's versions stay comparable (per-file normalisation
moved run 1's sections 1 LU apart): the loudest raw lands on --target (default -15 LUFS). If that
would push peaks more than --max-limit dB (default 3) into the limiter, it says so: put a glue
compressor on Live's master and re-render, or lower the target. Never 7 dB of offline limiting
(run 1 did, and the limiter moved the kick's attack by 15 ms). MP3: 44.1 kHz, CBR 192 kbps,
5 ms fade-in, 0.5 s fade-out; decoded true peak <= --tp-max (default -1.0 dBTP). Announcements
use lib/record/batch_intro.py's voice and loudness ("Track N." per track, the intro once).
upload: the R2 puts for the upload map (bucket as lib/record). Public: only with Anthony's go-ahead.
apply: prepends the entries to skrng/manifest.json and adds the batch to skrng/batches.json in a
site checkout; commit and PR there as usual.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_audio, write_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
BUCKET = "anthonybecker-audio"
WRANGLER = "wrangler@4.145.0"


def meter(x2: np.ndarray, sr: int) -> dict:
    from mlab import loudness as L

    return {"lufs": round(float(L.integrated(x2, sr)), 2), "true_peak_dbtp": round(float(L.true_peak(x2, sr)), 2),
            "sample_peak_dbfs": round(float(20 * np.log10(np.abs(x2).max() + 1e-15)), 2)}


def encode(raw: Path, out: Path, gain_db: float, ceiling_db: float, seconds: float) -> None:
    af = (f"volume={gain_db:.3f}dB,alimiter=limit={10 ** (ceiling_db / 20):.5f}:attack=5:release=60:level=0:latency=1,"
          f"afade=t=in:st=0:d=0.005,afade=t=out:st={max(0.0, seconds - 0.5):.3f}:d=0.5")
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", af, "-ar", "44100",
                    "-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3", str(out)], check=True)


def decode_meter(mp3: Path) -> dict:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "dec.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-c:a", "pcm_f32le", str(wav)], check=True)
        x2, sr = read_audio(wav, mono=False)
    return {**meter(x2, sr), "seconds": round(len(x2) / sr, 3)}


def prep(a) -> None:
    spec_path = Path(a.spec).expanduser()
    spec = json.loads(spec_path.read_text())
    out = Path(a.out).expanduser()
    (out / "tts").mkdir(parents=True, exist_ok=True)
    raws = []
    for t in spec["tracks"]:
        raw = (spec_path.parent / t["raw"]).resolve()
        x2, sr = read_audio(raw, mono=False)
        raws.append((t, raw, meter(x2, sr), len(x2) / sr))
    gain = a.target - max(m["lufs"] for _, _, m, _ in raws)
    ceiling = a.ceiling
    for _ in range(8):  # one gain and one ceiling for every track; the loudest MP3 lands on the target
        results = []
        for t, raw, m, secs in raws:
            mp3 = out / f"{t['id']}.mp3"
            encode(raw, mp3, gain, ceiling, secs)
            results.append({"id": t["id"], "raw": m, "mp3": decode_meter(mp3)})
        worst = max(r["mp3"]["true_peak_dbtp"] for r in results)
        short = a.target - max(r["mp3"]["lufs"] for r in results)
        if worst <= a.tp_max and abs(short) <= 0.2:
            break
        if worst > a.tp_max:
            ceiling -= 0.3
        if abs(short) > 0.2:
            gain += short
    else:
        raise SystemExit(f"no common gain met {a.target} LUFS and {a.tp_max} dBTP (last: {worst} dBTP, {short:+.2f} LU)")
    over = max(m["sample_peak_dbfs"] for _, _, m, _ in raws) + gain - ceiling
    lufs = [r["mp3"]["lufs"] for r in results]
    print(f"common gain {gain:+.2f} dB, ceiling {ceiling:.1f} dBFS: the loudest peak goes {over:.1f} dB into the limiter")
    print(f"MP3 LUFS {lufs} (spread {max(lufs) - min(lufs):.2f} LU), worst true peak {worst} dBTP")
    if over > a.max_limit:
        print(f"WARNING: {over:.1f} dB of limiting (> {a.max_limit}). Prefer glue on Live's master and a re-render, "
              "or a lower --target; see reference/publishing.md")

    sys.path.insert(0, str(ROOT / "lib" / "record"))
    from batch_intro import spoken_id, tts

    n = spec["batch"]
    entries, uploads = [], []
    for i, ((t, _, _, _), r) in enumerate(zip(raws, results), 1):
        ann = out / "tts" / f"{t['id']}.mp3"
        if not a.no_tts:
            tts(f"Track {i}.", ann)
        credit = spec["credit"]
        entries.append({"id": t["id"], "title": f"Tutorial practice — Track {i}: {t['label']}", "date": spec["date"],
                        "file": f"/audio/skrng/{t['id']}.mp3", "batch": n, "bpm": spec.get("bpm"),
                        "duration_s": round(r["mp3"]["seconds"], 1), "lufs": round(r["mp3"]["lufs"], 1),
                        "true_peak_dbtp": round(r["mp3"]["true_peak_dbtp"], 1), "notes": t["notes"],
                        "refs": [{"title": f"{credit['channel']} — {credit['title']}", "url": credit["url"]}],
                        "say": t["label"], "announce": f"/audio/skrng/tts/{t['id']}.mp3"})
        uploads += [{"local": f"{t['id']}.mp3", "r2_key": f"audio/skrng/{t['id']}.mp3", "content_type": "audio/mpeg"},
                    {"local": f"tts/{t['id']}.mp3", "r2_key": f"audio/skrng/tts/{t['id']}.mp3",
                     "content_type": "audio/mpeg"}]
    intro = f"{spoken_id(n)}. {spec['intro']}"
    key = f"batch-{str(n).replace('.', '-')}-{hashlib.md5(intro.encode()).hexdigest()[:6]}.mp3"
    if not a.no_tts:
        tts(intro, out / "tts" / key)
    uploads.append({"local": f"tts/{key}", "r2_key": f"audio/skrng/tts/{key}", "content_type": "audio/mpeg"})
    batch = {"n": n, "title": spec["batch_title"], "notes": spec["batch_notes"], "ordered": True,
             "announce": f"/audio/skrng/tts/{key}", "say": re.sub(r"^Batch [\d.]+(, part \d+)?\.\s*", "", intro)}
    doc = {"how_to_apply": "publish_prep.py upload (with Anthony's go-ahead), then publish_prep.py apply --site, "
                           "then a site PR. Local paths are relative to this file.",
           "uploaded": False, "common_gain_db": round(gain, 2), "ceiling_dbfs": round(ceiling, 2),
           "limit_over_ceiling_db": round(over, 1), "measurements": results,
           "manifest_entries": entries, "batch": batch, "uploads": uploads}
    write_json(out / "entries.json", doc)
    print(f"{len(entries)} entries, {len(uploads)} uploads -> {out / 'entries.json'} (nothing uploaded)")


def upload(a) -> None:
    path = Path(a.entries)
    doc = json.loads(path.read_text())
    for u in doc["uploads"]:
        cmd = ["npx", "-y", WRANGLER, "r2", "object", "put", f"{BUCKET}/{u['r2_key']}", "--file",
               str(path.parent / u["local"]), "--content-type", u["content_type"], "--remote"]
        print(" ".join(cmd))
        if a.yes:
            subprocess.run(cmd, check=True, capture_output=True)
    if a.yes:
        doc["uploaded"] = True
        write_json(path, doc)
        print(f"uploaded {len(doc['uploads'])} files")
    else:
        print("dry run: add --yes once uploads are permitted")


def apply(a) -> None:
    doc = json.loads(Path(a.entries).read_text())
    site = Path(a.site).expanduser()
    mf, bf = site / "skrng" / "manifest.json", site / "skrng" / "batches.json"
    manifest, batches = json.loads(mf.read_text()), json.loads(bf.read_text())
    ids = {e["id"] for e in manifest}
    if clash := [e["id"] for e in doc["manifest_entries"] if e["id"] in ids]:
        raise SystemExit(f"already in the manifest: {clash}")
    if any(b["n"] == doc["batch"]["n"] for b in batches):
        raise SystemExit(f"batch {doc['batch']['n']} already exists in batches.json")
    if not doc.get("uploaded"):
        print("WARNING: entries.json says the audio is not uploaded; the pages would 404 until it is")
    mf.write_text(json.dumps(doc["manifest_entries"] + manifest, indent=2, ensure_ascii=False) + "\n")
    bf.write_text(json.dumps(sorted(batches + [doc["batch"]], key=lambda b: b["n"]), indent=2, ensure_ascii=False) + "\n")
    print(f"added {len(doc['manifest_entries'])} entries and batch {doc['batch']['n']} in {site}; commit and PR there")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("spec")
    p.add_argument("--out", required=True)
    p.add_argument("--target", type=float, default=-15.0, help="LUFS of the loudest version")
    p.add_argument("--ceiling", type=float, default=-1.5, help="limiter ceiling, dBFS")
    p.add_argument("--tp-max", type=float, default=-1.0, help="decoded MP3 true peak, dBTP")
    p.add_argument("--max-limit", type=float, default=3.0, help="warn above this much limiting, dB")
    p.add_argument("--no-tts", action="store_true")
    p = sub.add_parser("upload")
    p.add_argument("entries")
    p.add_argument("--yes", action="store_true", help="really upload (public)")
    p = sub.add_parser("apply")
    p.add_argument("entries")
    p.add_argument("--site", required=True, help="a checkout of the site repo")
    a = ap.parse_args()
    {"prep": prep, "upload": upload, "apply": apply}[a.cmd](a)


if __name__ == "__main__":
    main()
