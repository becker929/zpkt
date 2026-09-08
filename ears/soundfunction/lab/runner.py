#!/usr/bin/env python3
"""The lab runner: fetch pending items from the site, measure them, post reports.

    LAB_TOKEN=... python3 lab/runner.py --base https://anthonybecker.me [--once] [--item ID]

Kinds and what they get:
  track / reference  grid (tempo, lock, bar one, kick on/off, breakdowns), pump on the mix
                     and on the separated bass stem, hits harvested from the drum stem and
                     named by the role model, kick pitch landing, stem levels; every number
                     next to the corpus median (corpus2/summary.json) and, for tracks, next
                     to the median of the owner's own reference items.
  sample             the seven measures plus the full feature set, the role model's answer,
                     and the medians of the synthetic and real libraries for that role.
  multitrack         each stem measured on its own (level, band shares, role of its hits),
                     the kick-like and bass-like stems found, and the true sidechain between
                     them measured with no guessing about the grid.
Reports are plain JSON in the shape private/lab/lab.js renders: headline, rows, sections.
"""
import argparse, json, os, sys, tempfile, time, traceback, urllib.request, urllib.error
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
CORPUS = json.load(open(ROOT / "corpus2" / "summary.json"))["all"]
LIB = {}


def api(base, token, path, method="GET", data=None, headers=None, raw=False):
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    body = None
    if data is not None and not raw:
        body = json.dumps(data).encode(); h["Content-Type"] = "application/json"
    elif data is not None:
        body = data
    req = urllib.request.Request(base + "/lab/api" + path, data=body, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=600) as r:
        ct = r.headers.get("Content-Type", "")
        return json.load(r) if "json" in ct else r.read()


def download(base, token, item, f, dest):
    req = urllib.request.Request(f"{base}/lab/api/items/{item['id']}/files/{urllib.request.quote(f['name'])}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as out:
        while True:
            b = r.read(1 << 20)
            if not b: break
            out.write(b)


def to_wav(src, dst, sr=44100):
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(sr), "-sample_fmt", "s16", str(dst)], check=True)


def longest_run(kick_on):
    best = cur = 0
    for k in kick_on:
        cur = cur + 1 if k else 0; best = max(best, cur)
    return best


def row(label, value, unit="", ref=None, note=""):
    return dict(label=label, value=None if value is None else (round(float(value), 3) if isinstance(value, (int, float, np.floating)) else value), unit=unit, ref=None if ref is None else round(float(ref), 3), note=note)


def library_medians():
    import csv
    if LIB: return LIB
    for name in ("library_synth", "library_real"):
        rows = list(csv.DictReader(open(ROOT / "out" / f"{name}.csv")))
        by = {}
        for r in rows:
            by.setdefault(r["sound"], []).append(r)
        LIB[name] = {k: {f: float(np.median([float(r[f]) for r in v if r[f] not in ("", "nan")])) for f in ("rise_10_90_ms", "decay40_ms", "sustain_share", "band_sub_share", "spectral_centroid_hz", "crest_factor_db")} for k, v in by.items()}
    return LIB


# ---------- reports ---------------------------------------------------------------

def report_track(paths, item, refs, work):
    from analysis import stems
    mix = paths[0]
    g = stems.grid_of(mix)
    parts = stems.separate(mix)   # cached by content under lab/cache
    bp = stems.bass_pump(parts["bass"], g)
    hits = stems.harvest_hits(parts["drums"])
    roles = stems.role_summary(hits, g["duration_s"])
    kicks = stems.kicks_by_position(parts["drums"], g, bass_path=parts["bass"])
    kp = kicks.get("landing_pitch_hz") or stems.kick_pitch(parts["drums"], hits)
    levels = stems.stem_levels(parts)
    sc = stems.sidechain_between(parts["drums"], parts["bass"]); sc.pop("curve_db", None)
    db = g["downbeat"]
    ref = lambda k: (refs or {}).get(k)
    from analysis.loudness import measure as loud
    import soundfile as sf
    ym, srm = sf.read(str(mix)); L = loud(ym, srm)
    bass_ok = levels.get("bass", -99) > -15
    bass_note = "" if bass_ok else f"NOT USABLE: the separator left the bass stem {abs(levels.get('bass', 0)):.0f} dB under the drums, so this reads a gap, not a pump"
    rows = [
        row("tempo", g["tempo"], "bpm", ref("tempo") or CORPUS["tempo_median"], "corpus median in the reference column when you have no references yet"),
        row("grid lock", g["lock"], "", None, "above 0.3 the beat grid is trustworthy"),
        row("integrated loudness", L["lufs"], "LUFS", ref("lufs"), "whole file, BS.1770; the corpus excerpts' median is in part four"),
        row("crest of the mix", L["crest_db"], "dB", ref("crest_db"), "peak over RMS of the whole file; lower means harder limiting"),
        row("bar one found with strength", db["beat_one_strength"], "", None, "1 = chance, 4 = every section change agrees"),
        row("pump on the mix", g["pump_mix"]["pump_depth_db"], "dB", ref("pump_depth_db") or CORPUS["pump_depth_median"]),
        row("pump on the bass stem", bp["pump_depth_db"], "dB", ref("bass_pump_depth_db"), bass_note or "the rumble alone, folded on the beat"),
        row("pump return time", bp["pump_return_ms"] if bass_ok else g["pump_mix"]["pump_return_ms"], "ms", ref("pump_return_ms") or CORPUS["pump_return_median"], "" if bass_ok else "from the mix, since the bass stem is not usable"),
        row("true sidechain, drums to bass", sc.get("pump_depth_db"), "dB", None, bass_note or f"bass low band folded on {sc.get('n_kicks', 0)} kick onsets from the drum stem"),
        row("bass energy below 60 Hz", bp.get("bass_sub_share"), "share", ref("bass_sub_share"), bass_note and "not usable"),
        row("kicks found by position", kicks.get("n"), "", None, f"{kicks.get('per_minute', 0)} per minute at {kicks.get('tempo', g['tempo']):.0f} bpm; beats where the drum stem has a strong onset"),
        row("kick lands on", kp, "Hz", ref("kick_pitch_hz"), f"pitch at about 100 ms; readable on {int(100 * kicks.get('pitch_readable_share', 0))}% of the loudest kicks"),
        row("kick: time to fall 20 dB", kicks.get("decay20_ms"), "ms", None, "median over the kicks found by position, measured over the whole beat"),
        row("kick: time to fall 40 dB", kicks.get("decay40_ms"), "ms", None, f"{int(100 * (kicks.get('decay40_hits_window') or 0))}% of kicks never fall 40 dB before the next beat ({kicks.get('beat_ms', 0):.0f} ms)"),
        row("kick: level at the next beat", kicks.get("level_at_next_beat_db"), "dB", None, "how much of the kick is still there when the next one lands; 0 = as loud as its peak"),
        row("kick: share below 60 Hz", kicks.get("band_sub_share"), "share", None, "after separation; the corpus kicks read 0.47"),
        row("kick: brightness", kicks.get("spectral_centroid_hz"), "Hz", None, "the corpus kicks read about 2100 Hz"),
        row("kick body: share below 60 Hz", (kicks.get("body") or {}).get("band_sub_share"), "share", None, "first 250 ms of drums and bass together: the kick as a one-shot would have it"),
        row("kick body: brightness", (kicks.get("body") or {}).get("spectral_centroid_hz"), "Hz", None, "same window"),
        row("kick body: falls 20 dB in", (kicks.get("body") or {}).get("decay20_ms"), "ms", None, "same window; 250 means it had not fallen 20 dB yet"),
        row("what the role model calls these kicks", ", ".join(f"{k} {v}" for k, v in (kicks.get("model_calls_them") or {}).items()) or None, "", None, "if it does not say kick, the model has not met this kind of kick"),
        row("bars with no kick", g["kick_off_share"], "share", ref("kick_off_share") or CORPUS["kick_off_share_median"]),
        row("longest kick run", longest_run(g["kick_on"]), "bars", None),
    ]
    sec_roles = dict(title="What the drum stem holds", text="Hits cut at onsets from the separated drums and named by the role model. Confidence is the model's own; below 0.5 treat the name as a guess.",
                     table=dict(columns=["job", "hits", "per minute", "confidence", "decay 40 dB (ms)", "sub share", "air share", "brightness (Hz)"],
                                rows=[[j, v["count"], v["per_minute"], v["mean_confidence"], v["decay40_ms"], v["band_sub_share"], v["band_air_share"], round(v["spectral_centroid_hz"])] for j, v in roles.items()]))
    sec_grid = dict(title="Where the attacks land in the bar", text="Six bands by sixteen steps, bar one at the left, averaged over the whole file.", grid=np.roll(np.array(g["profile_attack"]), -4 * db["beat_one"], axis=1).round(4).tolist())
    sec_stems = dict(title="Stem levels", text="Loudness of each separated stem below the loudest, in dB.", rows=[row(s, v, "dB") for s, v in levels.items()])
    offs = [r["length"] if isinstance(r, dict) else r for r in g.get("kick_off_runs", [])]
    sec_struct = dict(title="Structure", rows=[
        row("bars measured", g["n_bars"], "bars"), row("breakdowns (kick off 2+ bars)", len(offs), ""),
        row("longest breakdown", g.get("longest_off_bars", 0), "bars"), row("corpus: share of returns on the 8-bar line", CORPUS["return_on_8_line"], "share")])
    pump_word = f"pump {bp['pump_depth_db']:.0f} dB on the bass" if bass_ok and bp['pump_depth_db'] is not None else f"pump {g['pump_mix']['pump_depth_db']:.0f} dB on the mix"
    headline = f"{g['tempo']:.0f} bpm, {pump_word}, kick lands near {kp or '?'} Hz"
    report = dict(headline=headline, rows=rows, sections=[sec_roles, sec_grid, sec_stems, sec_struct],
                  raw=dict(tempo=g["tempo"], pump_depth_db=g["pump_mix"]["pump_depth_db"], bass_pump_depth_db=bp["pump_depth_db"] if bass_ok else None, pump_return_ms=bp["pump_return_ms"] if bass_ok else g["pump_mix"]["pump_return_ms"],
                           bass_sub_share=bp.get("bass_sub_share") if bass_ok else None, kick_pitch_hz=kp, lufs=L["lufs"], crest_db=L["crest_db"], kick_off_share=g["kick_off_share"], roles=roles, levels=levels, sidechain=sc, kicks=kicks, bass_ok=bass_ok))
    return report


def report_sample(paths, item, refs, work):
    from analysis.signal_features import describe_file
    from analysis.hits_extra import env_timings
    from analysis import stems
    import soundfile as sf
    f = describe_file(str(paths[0]))
    y, sr = sf.read(str(paths[0])); y = y.mean(axis=1) if y.ndim > 1 else y
    f.update(env_timings(y, sr))
    role, probs = stems.predict(f)
    fine = None
    lib = library_medians()
    real_role = {"kick": "kick", "rumble": "rumble", "hat": "hat_closed", "clap": "clap", "hook": "perc", "space": "impact"}[role]
    rs, rr = lib["library_synth"].get(real_role, {}), lib["library_real"].get(real_role, {})
    rows = [row("reads as", role, "", None, " · ".join(f"{k} {v:.2f}" for k, v in sorted(probs.items(), key=lambda x: -x[1])[:3]))]
    for k, lab, unit in [("rise_10_90_ms", "rise time", "ms"), ("decay40_ms", "time to fall 40 dB", "ms"), ("sustain_share", "energy after 50 ms", "share"),
                         ("band_sub_share", "share below 60 Hz", "share"), ("spectral_centroid_hz", "brightness", "Hz"), ("crest_factor_db", "crest", "dB")]:
        rows.append(row(lab, f.get(k), unit, rr.get(k), f"real {real_role} median; synthetic median {rs.get(k, float('nan')):.3g}"))
    rows += [row("pitch (median f0)", f.get("f0_hz"), "Hz"), row("pitch at 100 ms", f.get("f0_hz_at_100ms"), "Hz"), row("duration to -60 dB", f.get("duration_s"), "s")]
    return dict(headline=f"This reads as a {role} ({probs[role]:.0%})", rows=rows, sections=[dict(title="All measures", table=dict(columns=["measure", "value"], rows=[[k, round(v, 4) if isinstance(v, float) else v] for k, v in sorted(f.items())]))],
                raw=dict(role=role, probs=probs, features=f))


def report_multitrack(paths, item, refs, work):
    from analysis import stems, grid
    import librosa
    per = []
    for p in paths:
        y, _ = librosa.load(str(p), sr=grid.SR, mono=True); dur = len(y) / grid.SR
        if not np.any(y):
            per.append(dict(name=p.name, silent=True)); continue
        env, atk = grid.envelopes(y); tot = env.sum(axis=1) + 1e-12; shares = (tot / tot.sum()).round(3)
        level = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12))
        sub_attacks = float(atk[0].sum()); air_attacks = float(atk[5].sum())
        hits = stems.harvest_hits(str(p), max_hits=300) if dur > 3 else []
        roles = stems.role_summary(hits, dur)
        top = max(roles, key=lambda k: roles[k]["count"]) if roles else None
        if dur <= 3:
            f = stems.fast_features(librosa.load(str(p), sr=44100, mono=True)[0])
            top = stems.predict(f)[0] if f else None
        per.append(dict(name=p.name, duration_s=round(dur, 1), level_db=round(level, 1), shares=shares.tolist(), sub_attacks=sub_attacks, air_attacks=air_attacks,
                        sustained_low=float(np.median(env[1]) / (np.max(env[1]) + 1e-12)), top_role=top, n_hits=len(hits), roles=roles))
    live = [s for s in per if not s.get("silent")]
    # the kick-like stem: most hits the role model calls kicks, sub attacks as the tie-break
    kick = max(live, key=lambda s: (s["roles"].get("kick", {}).get("count", 0), s["sub_attacks"])) if live else None
    bass = max([s for s in live if s is not kick], key=lambda s: s["shares"][0] + s["shares"][1] + s["sustained_low"], default=None)
    sc = stems.sidechain_between(str([p for p in paths if p.name == kick["name"]][0]), str([p for p in paths if p.name == bass["name"]][0])) if kick and bass else {}
    sc.pop("curve_db", None)
    rows = [row("stems", len(paths), ""), row("kick-like stem", kick["name"] if kick else None), row("bass-like stem", bass["name"] if bass else None),
            row("sidechain depth, kick into bass", sc.get("pump_depth_db"), "dB", CORPUS["pump_depth_median"], "corpus pump median for scale; on real stems this is the true ducking"),
            row("sidechain return", sc.get("pump_return_ms"), "ms", CORPUS["pump_return_median"]), row("kick interval", sc.get("kick_interval_ms"), "ms")]
    table = dict(columns=["stem", "length (s)", "level (dB)", "sub", "low", "mid", "high", "air", "reads as", "hits"],
                 rows=[[s["name"], s.get("duration_s"), s.get("level_db"), *(s["shares"][i] for i in (0, 1, 3, 4, 5)), s.get("top_role"), s.get("n_hits")] if not s.get("silent") else [s["name"], 0, None, None, None, None, None, None, "silent", 0] for s in per])
    return dict(headline=f"{len(paths)} stems; sidechain from {kick['name'] if kick else '?'} into {bass['name'] if bass else '?'} is {sc.get('pump_depth_db', '?')} dB",
                rows=rows, sections=[dict(title="Each stem", text="Band shares are of that stem's own energy. 'Reads as' is the role model's most common answer for hits in the stem, or its answer for the whole file when it is a single hit.", table=table)],
                raw=dict(stems=per, sidechain=sc))


def reference_medians(base, token):
    """Medians of the owner's own reference items' raw numbers, for the reference column."""
    items = api(base, token, "/items?status=done")["items"]
    vals = {}
    for it in items:
        if it["kind"] != "reference": continue
        full = api(base, token, f"/items/{it['id']}")
        raw = (full.get("report") or {}).get("raw") or {}
        for k in ("tempo", "pump_depth_db", "bass_pump_depth_db", "pump_return_ms", "bass_sub_share", "kick_pitch_hz", "kick_off_share"):
            if raw.get(k) is not None: vals.setdefault(k, []).append(raw[k])
    return {k: float(np.median(v)) for k, v in vals.items()}


def run_item(base, token, item):
    api(base, token, f"/items/{item['id']}", "PATCH", {"status": "running", "error": None})
    with tempfile.TemporaryDirectory() as td:
        work = Path(td); paths = []
        (work / "raw").mkdir(); (work / "wav").mkdir()
        for f in item["files"]:
            raw = work / "raw" / f["name"]; download(base, token, item, f, raw)
            wav = work / "wav" / (Path(f["name"]).stem + ".wav")   # mono 44.1k, whatever came in
            to_wav(raw, wav); paths.append(wav)
        refs = reference_medians(base, token) if item["kind"] == "track" else {}
        fn = {"track": report_track, "reference": report_track, "sample": report_sample, "multitrack": report_multitrack}[item["kind"]]
        t0 = time.time(); report = fn(paths, item, refs, work); report["runner"] = dict(seconds=round(time.time() - t0, 1), when=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        api(base, token, f"/items/{item['id']}/results", "PUT", report)
    return report


AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a", ".opus"}


def run_local(src, out):
    """No site involved: walk a folder and write one report per item into `out`.
    Layout:  refs/*.ext            each file a reference track
             tracks/*.ext          each file a track or demo
             samples/*.ext         each file a single hit
             stems/<name>/*.ext    each folder one multitrack item
    Anything else at the top level is treated as a track."""
    src, out = Path(src), Path(out); out.mkdir(parents=True, exist_ok=True)
    items = []
    for d in sorted(src.iterdir()):
        if d.is_dir() and d.name.lower() in ("refs", "references", "reference"):
            items += [dict(kind="reference", title=f.stem, files=[f]) for f in sorted(d.iterdir()) if f.suffix.lower() in AUDIO_EXT]
        elif d.is_dir() and d.name.lower() in ("tracks", "demos", "track"):
            items += [dict(kind="track", title=f.stem, files=[f]) for f in sorted(d.iterdir()) if f.suffix.lower() in AUDIO_EXT]
        elif d.is_dir() and d.name.lower() in ("samples", "sample", "hits"):
            items += [dict(kind="sample", title=f.stem, files=[f]) for f in sorted(d.iterdir()) if f.suffix.lower() in AUDIO_EXT]
        elif d.is_dir() and d.name.lower() in ("stems", "multitrack", "multitracks"):
            for sub in sorted(d.iterdir()):
                if sub.is_dir():
                    fs = [f for f in sorted(sub.iterdir()) if f.suffix.lower() in AUDIO_EXT]
                    if fs: items.append(dict(kind="multitrack", title=sub.name, files=fs))
        elif d.is_file() and d.suffix.lower() in AUDIO_EXT:
            items.append(dict(kind="track", title=d.stem, files=[d]))
    # references first so tracks can be compared against them
    items.sort(key=lambda i: {"reference": 0, "sample": 1, "multitrack": 2, "track": 3}[i["kind"]])
    ref_lists, refs, done = {}, {}, []
    def note_ref(rep):
        for k in ("tempo", "pump_depth_db", "bass_pump_depth_db", "pump_return_ms", "bass_sub_share", "kick_pitch_hz", "kick_off_share", "lufs", "crest_db"):
            if (rep.get("raw") or {}).get(k) is not None: ref_lists.setdefault(k, []).append(rep["raw"][k])
        refs.clear(); refs.update({k: float(np.median(v)) for k, v in ref_lists.items()})
    for it in items:
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in f"{it['kind']}-{it['title']}")[:80]
        if (out / f"{slug}.json").exists():   # resume: keep what an earlier run finished
            rep = json.load(open(out / f"{slug}.json")); done.append(rep)
            if it["kind"] == "reference": note_ref(rep)
            print(f"have {it['kind']}: {it['title']}", file=sys.stderr, flush=True); continue
        print(f"running {it['kind']}: {it['title']} ({len(it['files'])} files)", file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory() as td:
            work = Path(td); (work / "wav").mkdir(); paths = []
            for f in it["files"]:
                wav = work / "wav" / (f.stem + ".wav"); to_wav(f, wav); paths.append(wav)
            fn = {"track": report_track, "reference": report_track, "sample": report_sample, "multitrack": report_multitrack}[it["kind"]]
            t0 = time.time()
            try:
                rep = fn(paths, it, refs if it["kind"] == "track" else {}, work)
            except Exception as e:
                traceback.print_exc(); rep = dict(headline=f"failed: {type(e).__name__}: {e}", rows=[], sections=[], raw={})
            rep["runner"] = dict(seconds=round(time.time() - t0, 1), when=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            rep["item"] = dict(kind=it["kind"], title=it["title"], files=[f.name for f in it["files"]])
            json.dump(rep, open(out / f"{slug}.json", "w"), indent=1); done.append(rep)
            print(f"  {rep['headline']}  ({rep['runner']['seconds']} s)", file=sys.stderr, flush=True)
        if it["kind"] == "reference": note_ref(rep)
    json.dump(done, open(out / "all.json", "w"), indent=1)
    print(f"{len(done)} reports in {out}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="https://anthonybecker.me"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--item"); ap.add_argument("--poll", type=int, default=120)
    ap.add_argument("--local", help="analyse a local folder instead of the site (see run_local)"); ap.add_argument("--out", default="lab/reports")
    a = ap.parse_args()
    if a.local:
        run_local(a.local, a.out); return
    token = os.environ.get("LAB_TOKEN")
    if not token: sys.exit("LAB_TOKEN is not set")
    while True:
        items = api(a.base, token, "/items?status=pending")["items"]
        if a.item: items = [i for i in items if i["id"] == a.item] or [api(a.base, token, f"/items/{a.item}")]
        for it in items:
            print(f"running {it['id']} ({it['kind']}, {len(it['files'])} files)", file=sys.stderr, flush=True)
            try:
                rep = run_item(a.base, token, it); print(f"  done: {rep['headline']}", file=sys.stderr, flush=True)
            except Exception as e:
                traceback.print_exc()
                try: api(a.base, token, f"/items/{it['id']}", "PATCH", {"status": "failed", "error": f"{type(e).__name__}: {e}"})
                except Exception: pass
        if a.once or a.item: break
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
