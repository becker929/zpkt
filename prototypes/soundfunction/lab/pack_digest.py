#!/usr/bin/env python3
"""Digest a folder of one-shots: every file measured with the portable features and named by
the role model; a digest per sub-folder; and, when reference reports exist, the kicks ranked by
how close they sit to the references' kick profile.

    python3 lab/pack_digest.py lab/drive/files/samples lab/drive/reports/pack.json [lab/drive/reports/all.json]

Writes the per-file CSV next to the JSON and returns a report in the bench-sheet shape so
lab/report_html.py can render it as one more item.
"""
import csv, json, sys, os, math
from pathlib import Path
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
AUDIO = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a"}
KEYS = ["decay20_ms", "decay40_ms", "sustain_share", "band_sub_share", "band_low_share", "band_lowmid_share", "band_mid_share", "band_high_share", "band_air_share", "spectral_centroid_hz", "spectral_centroid_hz_100ms", "centroid_slope_hz_per_ms", "crest_factor_db"]


def one(path):
    import librosa
    from analysis import stems
    try:
        y, _ = librosa.load(path, sr=44100, mono=True, duration=4.0)
        if not np.any(y): return dict(file=path, error="silent")
        y = y / (np.abs(y).max() + 1e-9)
        f = stems.fast_features(y)
        if not f: return dict(file=path, error="no features")
        role, probs = stems.predict(f)
        return dict(file=path, folder=str(Path(path).parent.relative_to(ROOT_DIR)), name=Path(path).name, seconds=round(len(y) / 44100, 3), role=role, conf=round(probs[role], 3), **{k: round(float(f[k]), 5) for k in KEYS})
    except Exception as e:
        return dict(file=path, error=f"{type(e).__name__}: {e}")


ROOT_DIR = None


def main(src, out_json, all_json=None, workers=4):
    global ROOT_DIR; ROOT_DIR = Path(src)
    files = sorted(str(p) for p in ROOT_DIR.rglob("*") if p.suffix.lower() in AUDIO and not p.name.startswith("."))
    print(f"{len(files)} audio files", file=sys.stderr)
    with Pool(workers, initializer=_init, initargs=(str(ROOT_DIR),)) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(one, files, chunksize=8), 1):
            rows.append(r)
            if i % 500 == 0: print(f"  {i}/{len(files)}", file=sys.stderr, flush=True)
    ok = [r for r in rows if "error" not in r]
    csv_path = Path(out_json).with_suffix(".csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ok[0].keys()) if ok else ["file"]); w.writeheader(); w.writerows(ok)
    # digest per folder
    folders = {}
    for r in ok: folders.setdefault(r["folder"], []).append(r)
    med = lambda rs, k: round(float(np.median([r[k] for r in rs])), 3)
    table_rows = []
    for name, rs in sorted(folders.items()):
        votes = {}
        for r in rs: votes[r["role"]] = votes.get(r["role"], 0) + 1
        top = max(votes, key=votes.get)
        table_rows.append([name, len(rs), f"{top} {votes[top]}/{len(rs)}", med(rs, "decay20_ms"), med(rs, "band_sub_share"), med(rs, "band_mid_share"), round(med(rs, "spectral_centroid_hz")), med(rs, "crest_factor_db")])
    sections = [dict(title="Each folder", text="What the role model calls most files in the folder, and the folder's middle values. Sub and mid are shares of the file's own energy.",
                     table=dict(columns=["folder", "files", "model's top call", "falls 20 dB (ms)", "sub share", "mid share", "brightness (Hz)", "crest (dB)"], rows=table_rows))]
    rows_out = [dict(label="files measured", value=len(ok), unit="", ref=None, note=f"{len(rows) - len(ok)} skipped (silent or unreadable)"),
                dict(label="folders", value=len(folders), unit="", ref=None, note="")]
    # kicks ranked against the references' kick profile
    if all_json and os.path.exists(all_json):
        reps = json.load(open(all_json))
        refk = [r["raw"]["kicks"]["body"] for r in reps if r.get("item", {}).get("kind") == "reference" and ((r.get("raw") or {}).get("kicks") or {}).get("body")]
        if refk:
            prof = {k: float(np.median([x[k] for x in refk])) for k in ("decay20_ms", "band_sub_share", "band_mid_share", "spectral_centroid_hz", "crest_factor_db")}
            # spreads from the corpus hit library so no one measure dominates
            lib = list(csv.DictReader(open(Path(__file__).resolve().parent.parent / "out" / "library_corpus.csv")))
            kicks_lib = [x for x in lib if x["sound"] == "kick"]
            spread = {k: (np.std([float(x[k]) for x in kicks_lib]) or 1.0) for k in prof}
            cands = [r for r in ok if ("bassdrum" in r["folder"].lower() or "kick" in r["folder"].lower() or "kick" in r["name"].lower()) and r["seconds"] >= 0.15]
            import librosa
            from analysis import stems as _st
            for r in cands:
                yk, _ = librosa.load(r["file"], sr=44100, mono=True, duration=0.25); yk = yk / (np.abs(yk).max() + 1e-9)
                fb = _st.fast_features(yk) or {}
                for k in prof: r[k] = round(float(fb.get(k, r[k])), 5)
                r["_d"] = math.sqrt(sum(((r[k] - prof[k]) / spread[k]) ** 2 for k in prof))
            cands.sort(key=lambda r: r["_d"])
            best = cands[:25]
            sections.append(dict(title="Kicks nearest your references", text="The references' kick body (first 250 ms of drums and bass together at each on-beat kick, median over the references: fall to 20 dB, sub and mid share, brightness, crest) and the pack's kicks ranked by distance to it, measured over the same 250 ms. Distances are in corpus standard deviations; under 2 is close.",
                                 rows=[dict(label=f"reference profile: {k}", value=round(v, 3), unit="", ref=None, note="") for k, v in prof.items()],
                                 table=dict(columns=["kick", "folder", "distance", "falls 20 dB (ms)", "sub", "mid", "brightness", "crest"],
                                            rows=[[r["name"], r["folder"], round(r["_d"], 2), r["decay20_ms"], r["band_sub_share"], r["band_mid_share"], round(r["spectral_centroid_hz"]), r["crest_factor_db"]] for r in best])))
            rows_out.append(dict(label="kick candidates ranked", value=len(cands), unit="", ref=None, note="files in a kick folder, named kick, or read as kick by the model"))
    report = dict(item=dict(kind="pack", title=ROOT_DIR.name, files=[f"{len(files)} files"]), headline=f"{len(ok)} one-shots in {len(folders)} folders, measured and named",
                  rows=rows_out, sections=sections, raw=dict(csv=str(csv_path)))
    json.dump(report, open(out_json, "w"), indent=1); print("wrote", out_json, "and", csv_path, file=sys.stderr)


def _init(root):
    global ROOT_DIR; ROOT_DIR = Path(root)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
