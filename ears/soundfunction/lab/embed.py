#!/usr/bin/env python3
"""Where do the owner's tracks sit among 215 corpus tracks and the references?

One vector per track from the same code on the same kind of audio (separated stems, band-limited
to 11 kHz so the corpus's 22 kHz excerpts and the owner's 44 kHz files are comparable):
tempo, pump on the mix, share of kick-free bars, kick fall to 20 dB, kick level at the next beat,
kick sub / mid share and brightness, kick body sub share / brightness / fall, landing pitch,
bass and 'other' stem level relative to drums. Standardised on the corpus, PCA to two axes.

    python3 lab/embed.py [--workers 3]   -> lab/drive/reports/embedding.json, out/plots/embedding.png
"""
import argparse, json, sys, glob, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent
FEATS = ["tempo", "pump_mix", "kick_off_share", "k_decay20", "k_ring_db", "k_sub", "k_mid", "k_bright", "body_sub", "body_bright", "body_decay20", "kick_pitch", "bass_rel_db", "other_rel_db"]
NAMES = {"tempo": "tempo", "pump_mix": "pump (mix)", "kick_off_share": "kick-free bars", "k_decay20": "kick fall 20 dB", "k_ring_db": "kick at next beat", "k_sub": "kick sub share",
         "k_mid": "kick mid share", "k_bright": "kick brightness", "body_sub": "kick body sub", "body_bright": "kick body brightness", "body_decay20": "kick body fall", "kick_pitch": "landing pitch",
         "bass_rel_db": "bass vs drums", "other_rel_db": "other vs drums"}


def bandlimited(path, tmpdir):
    """Resample to 22050 and back so every file has the corpus excerpts' bandwidth."""
    import librosa, soundfile as sf
    y, sr = librosa.load(path, sr=22050, mono=True)
    out = Path(tmpdir) / (Path(path).parent.name + "-" + Path(path).name)
    sf.write(out, librosa.resample(y, orig_sr=22050, target_sr=44100), 44100); return str(out)


def one(job):
    """job: (label, kind, drums, bass, other, mixstats) -> vector"""
    import tempfile
    from analysis import stems
    label, kind, drums, bass, other, mix = job
    try:
        with tempfile.TemporaryDirectory() as td:
            d, b = bandlimited(drums, td), bandlimited(bass, td)
            k = stems.kicks_by_position(d, None, bass_path=b)
            lv = stems.stem_levels({"drums": drums, "bass": bass, "other": other})
        body = k.get("body") or {}
        v = dict(tempo=k.get("tempo") or mix.get("tempo"), pump_mix=mix.get("pump_mix"), kick_off_share=mix.get("kick_off_share"),
                 body_lowmid=body.get("band_lowmid_share"), body_mid=body.get("band_mid_share"), body_high=body.get("band_high_share"), body_air=body.get("band_air_share"), body_low=body.get("band_low_share"), body_slope=body.get("centroid_slope_hz_per_ms"), body_crest=body.get("crest_factor_db"),
                 k_decay20=k.get("decay20_ms"), k_ring_db=k.get("level_at_next_beat_db"), k_sub=k.get("band_sub_share"), k_mid=k.get("band_mid_share"), k_bright=k.get("spectral_centroid_hz"),
                 body_sub=body.get("band_sub_share"), body_bright=body.get("spectral_centroid_hz"), body_decay20=body.get("decay20_ms"), kick_pitch=k.get("landing_pitch_hz"),
                 bass_rel_db=lv.get("bass"), other_rel_db=lv.get("other"))
        return dict(label=label, kind=kind, ok=True, **v)
    except Exception as e:
        return dict(label=label, kind=kind, ok=False, error=f"{type(e).__name__}: {e}")


def jobs():
    out = []
    S = json.load(open(ROOT / "corpus2" / "stems_results.json")); keep = {t["id"]: t for t in json.load(open(ROOT / "corpus2" / "summary.json"))["tracks"]}
    M = {m["id"]: m for m in json.load(open(ROOT / "corpus2" / "manifest.json"))}
    for r in S:
        if r["id"] not in keep: continue
        d = ROOT / "corpus2" / "stems" / r["id"]
        if not (d / "drums.wav").exists(): continue
        m = M.get(r["id"], {}); label = f"{m.get('artist', '?')} – {m.get('title', r['id'])}"
        out.append((label, "corpus", str(d / "drums.wav"), str(d / "bass.wav"), str(d / "other.wav"), dict(tempo=r["tempo"], pump_mix=r["pump_mix"], kick_off_share=r.get("kick_off_share"))))
    # the owner's items: cached separations, matched by title through the reports
    reps = json.load(open(ROOT / "lab" / "drive" / "reports" / "all.json"))
    for rep in reps:
        it = rep["item"]
        if it["kind"] not in ("track", "reference"): continue
        hits = glob.glob(str(ROOT / "lab" / "cache" / "*" / "htdemucs" / it["title"] / "drums.wav"))
        if not hits: continue
        d = Path(hits[0]).parent; raw = rep.get("raw") or {}
        out.append((it["title"], it["kind"], str(d / "drums.wav"), str(d / "bass.wav"), str(d / "other.wav"), dict(tempo=raw.get("tempo"), pump_mix=raw.get("pump_depth_db"), kick_off_share=raw.get("kick_off_share"))))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=3); a = ap.parse_args()
    J = jobs(); print(len(J), "tracks to embed", file=sys.stderr)
    with Pool(a.workers, maxtasksperchild=6) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(one, J), 1):
            rows.append(r)
            if i % 25 == 0: print(f"  {i}/{len(J)}", file=sys.stderr, flush=True)
    ok = [r for r in rows if r["ok"]]
    X = np.array([[np.nan if r.get(f) is None else float(r[f]) for f in FEATS] for r in ok])
    corp = np.array([r["kind"] == "corpus" for r in ok])
    med = np.nanmedian(X[corp], axis=0); X = np.where(np.isnan(X), med, X)
    mu, sd = X[corp].mean(0), X[corp].std(0) + 1e-9; Z = (X - mu) / sd
    Zc = Z[corp]; U, s, Vt = np.linalg.svd(Zc - Zc.mean(0), full_matrices=False)
    P = (Z - Zc.mean(0)) @ Vt[:2].T; explained = (s[:2] ** 2 / (s ** 2).sum()).round(3).tolist()
    loadings = {f: [round(float(Vt[0, i]), 3), round(float(Vt[1, i]), 3)] for i, f in enumerate(FEATS)}
    # nearest corpus neighbours of every owner item, in the full standardised space
    out_rows = []
    for i, r in enumerate(ok):
        extra = ["body_lowmid", "body_mid", "body_high", "body_air", "body_low", "body_slope", "body_crest"]
        item = dict(label=r["label"], kind=r["kind"], x=round(float(P[i, 0]), 3), y=round(float(P[i, 1]), 3), values={f: (None if r.get(f) is None else round(float(r[f]), 3)) for f in FEATS + extra})
        if r["kind"] != "corpus":
            dist = np.sqrt(((Z[corp] - Z[i]) ** 2).sum(1)); idx = np.argsort(dist)[:3]
            item["nearest"] = [dict(label=ok[j]["label"], distance=round(float(dist[k]), 2)) for k, j in zip(idx, np.flatnonzero(corp)[idx])]
            item["z"] = {f: round(float(Z[i, k]), 2) for k, f in enumerate(FEATS)}
        out_rows.append(item)
    res = dict(features=FEATS, names=NAMES, explained=explained, loadings=loadings, corpus_mean=dict(zip(FEATS, mu.round(3).tolist())), corpus_sd=dict(zip(FEATS, sd.round(3).tolist())), items=out_rows, failed=[r for r in rows if not r["ok"]])
    (ROOT / "lab" / "drive" / "reports").mkdir(parents=True, exist_ok=True)
    json.dump(res, open(ROOT / "lab" / "drive" / "reports" / "embedding.json", "w"), indent=1)
    print(f"{len(ok)} embedded, {len(res['failed'])} failed; axes explain {explained}", file=sys.stderr)


if __name__ == "__main__":
    main()
