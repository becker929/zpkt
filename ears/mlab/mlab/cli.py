"""Command line: python3 -m mlab <command> ...   (run from the lab root)."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from . import io as aio
from .util import r

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out(obj, as_json):
    if as_json:
        print(json.dumps(obj, indent=2, default=aio._json_default))
    return obj


def _stem(p):
    return os.path.splitext(os.path.basename(p))[0]


def cmd_measure(a):
    from . import measure
    au = aio.load(a.file)
    sh = measure.sheet(au, codecs=a.codecs)
    md = measure.markdown(sh, os.path.basename(a.file))
    base = os.path.join(LAB, "reports", _stem(a.file))
    aio.dump_json(sh, base + ".json")
    with open(base + ".md", "w") as f:
        f.write(md)
    if a.json:
        _out(sh, True)
    else:
        print(md)
        print(f"(saved {os.path.relpath(base, LAB)}.md / .json)")


def cmd_premaster(a):
    from . import premaster
    res = premaster.run(aio.load(a.file))
    if a.json:
        return _out(res, True)
    print(f"Premaster check: {os.path.basename(a.file)} -> {res['overall']}\n")
    for row in res["checks"]:
        print(f"  [{row['status']:4}] {row['check']:30} {str(row['value']):>10}   {row['why']}")


def cmd_deliver(a):
    from . import delivery, loudness as L
    au = aio.load(a.file)
    res = delivery.report(au.x, au.sr, codecs=not a.no_codecs)
    if a.json:
        return _out(res, True)
    print(f"Delivery: {os.path.basename(a.file)}  I={res['integrated']} LUFS  TP={res['true_peak']} dBTP\n")
    for p, v in res["normalization"].items():
        print(f"  {p:13} gain {str(v['gain_db']):>6} dB -> {str(v['playback_lufs']):>6} LUFS, {str(v['playback_true_peak']):>6} dBTP   ({v['note']})")
    for c, v in res.get("codec_roundtrip", {}).items():
        print(f"  codec {c:8} {v}")
    for adv in res["advice"]:
        print("  ! " + adv)


def cmd_bitdepth(a):
    from . import bitdepth
    _out(bitdepth.analyze(aio.load(a.file)), True)


def cmd_spectrum(a):
    from . import spectrum as S
    au = aio.load(a.file)
    tb = S.tonal_balance(au.x, au.sr)
    out = {"slope_db_per_oct": tb["slope_db_per_oct"], "groups": tb["groups_db_rel_total"],
           "stereo": S.stereo_by_band(au.x, au.sr)}
    if a.ref:
        rf = aio.load(a.ref)
        out["difference_vs_ref_third_octave"] = S.compare(au.x, rf.x, au.sr, rf.sr)
    if a.phon is not None:
        out["perceived_change_vs_%s_phon" % a.ref_phon] = S.perceived_balance(tb["third_octave"], a.phon, a.ref_phon)
    _out(out, True)


def cmd_eqdiff(a):
    from . import spectrum as S
    d, w = aio.load(a.dry), aio.load(a.wet)
    dd, ww, lag = S.align(d.x, w.x, sr=d.sr)
    res = S.eq_diff(dd, ww, d.sr)
    summ = S.summarize_eq(res)
    summ["latency_samples"] = lag
    if a.json:
        return _out({"summary": summ, "curve": res}, True)
    _out(summ, True)


def cmd_compprobe(a):
    from . import dynamics as D, spectrum as S
    d, w = aio.load(a.dry), aio.load(a.wet)
    dd, ww, lag = D.probe_align(d.x, w.x)
    res = D.comp_probe(dd, ww, d.sr)
    res["latency_samples"] = lag
    _out(res, True)


def cmd_probe(a):
    from . import siggen
    out = os.path.join(LAB, "audio", "renders", "probes")
    x, lay = siggen.comp_probe(a.sr)
    aio.save(os.path.join(out, "comp_probe.wav"), x, a.sr, "PCM_24")
    aio.dump_json(lay, os.path.join(out, "comp_probe.layout.json"))
    aio.save(os.path.join(out, "eq_probe_pink.wav"), siggen.eq_probe(a.sr), a.sr, "PCM_24")
    print(f"wrote probes to {os.path.relpath(out, LAB)}/ (drag into Live, render through the device, export 32-bit float)")


def cmd_match(a):
    from . import compare
    auds = [aio.load(p) for p in a.files]
    res, tgt = compare.match(auds, a.target)
    out = os.path.join(LAB, "audio", "renders", "matched")
    for au, (x, g) in zip(auds, res):
        p = os.path.join(out, f"{_stem(au.path)}_@{r(tgt, 1)}LUFS.wav")
        aio.save(p, x, au.sr)
        print(f"{os.path.basename(au.path)}: {r(g):+} dB -> {os.path.relpath(p, LAB)}")


def cmd_abx(a):
    from . import compare
    out = a.out or os.path.join(LAB, "audio", "renders", "abx", f"{_stem(a.a)}_vs_{_stem(a.b)}")
    compare.abx_kit(aio.load(a.a), aio.load(a.b), out, a.trials, a.start, a.dur)
    print(f"ABX kit: {os.path.relpath(out, LAB)}  (see HOW_TO.md; do not open .answer_key.json)")


def cmd_abxscore(a):
    from . import compare
    _out(compare.abx_score(a.folder, a.answers), True)


def cmd_kcal(a):
    from . import siggen
    out = os.path.join(LAB, "audio", "renders", "k-system")
    for name, x in siggen.kcal_files(a.sr).items():
        aio.save(os.path.join(out, name), x, a.sr, "PCM_24")
    print(f"wrote K-System calibration noise to {os.path.relpath(out, LAB)}/ — see guides/ch20-21-monitoring.md")


def cmd_als(a):
    from . import als
    s = als.read(a.file)
    if a.json:
        return _out(s, True)
    print(f"{os.path.basename(a.file)} — {s['creator']} — {s['tempo']} BPM — main fader {s['main_volume_db']} dB")
    print("Main chain: " + (", ".join(f"{d['device']}{'' if d['on'] else ' (off)'}" for d in s["main_devices"]) or "(empty)"))
    for t in s["tracks"]:
        devs = ", ".join(f"{d['device']}{'' if d['on'] else ' (off)'}" for d in t["devices"])
        print(f"  {t['type'][:5]:5} {t['name'][:40]:40} {str(t['volume_db']):>7} dB {'' if t['active'] else '[deactivated]'}  {devs}")
    for f in s["findings"]:
        print("  ! " + f)


def _ref_paths(folder):
    return [p for p in sorted(glob.glob(os.path.join(folder, "*")))
            if os.path.splitext(p)[1].lower() in (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a")]


def cmd_refs(a):
    if a.peaks:
        return _refs_peaks(a)
    from . import compare, measure
    t = measure.flat(measure.sheet(aio.load(a.file)))
    refs = {_stem(p)[:18]: measure.flat(measure.sheet(aio.load(p))) for p in _ref_paths(a.refs)}
    print(compare.refs_table(t, refs, measure.CORE_KEYS))


def _refs_peaks(a):
    """Section-aware comparison: structure, then peak window against peak window."""
    import numpy as np
    import soundfile as sf
    from . import loudness as L
    from . import sections as SE

    def load(p):
        au = aio.load(p)
        an = SE.analyze(au.x, au.sr)
        prof = SE.peak_profile(au.x, au.sr, an["bpm"], an["peak_bars"]) if an["peak_bars"] else None
        return au, an, prof

    tgt = load(a.file)
    refs = {_stem(p)[:18]: load(p) for p in _ref_paths(a.refs)}
    rows = {"TARGET " + _stem(a.file)[:11]: tgt, **refs}
    out = {"structure": {k: v[1] for k, v in rows.items()}}

    print("Structure (bars, 1-based)\n")
    print(f"{'track':<19}{'BPM':>7}{'bars':>6}  {'main break':<12}{'peak':<12}{'drop vs peak':>13}  peak after break")
    for k, (_, an, _) in rows.items():
        print(f"{k:<19}{an['bpm']:>7.2f}{an['bars']:>6}  {str(an['main_break']):<12}{str(an['peak_bars']):<12}"
              f"{an['drop_vs_peak_high_db'] if an['drop_vs_peak_high_db'] is not None else '-':>13}  {an['peak_after_main_break']}")

    tp = tgt[2]
    rp = {k: v[2] for k, v in refs.items() if v[2]}
    if tp and rp:
        print("\nPeak window, level-independent\n")
        print(f"{'track':<19}{'LUFS':>7}{'crest':>7}{'corr<120':>10}{'S-M<120':>9}")
        for k, (_, _, p) in rows.items():
            if p:
                print(f"{k:<19}{p['lufs']:>7.2f}{p['crest_median_db']:>7.2f}{p['low_corr']:>10.3f}{p['low_side_minus_mid_db']:>9.1f}")
        fc = [c for c, _ in tp["third_octave_rel"]]
        tv = np.array([v for _, v in tp["third_octave_rel"]])
        R = np.array([[v for _, v in p["third_octave_rel"][:len(fc)]] for p in rp.values()])
        d = tv[None, :R.shape[1]] - R
        print("\nTarget minus each reference, 1/3 octave, equal total energy (dB)\n")
        print(f"{'Hz':>7}" + "".join(f"{k[:9]:>10}" for k in rp) + f"{'mean':>8}  flag")
        bands = []
        for i in range(d.shape[1]):
            col = d[:, i]
            flag = "below all" if col.max() < -2 else "above all" if col.min() > 2 else ""
            bands.append({"hz": fc[i], "diff": [round(float(v), 2) for v in col], "mean": round(float(col.mean()), 2), "flag": flag})
            print(f"{fc[i]:>7.0f}" + "".join(f"{v:>10.1f}" for v in col) + f"{col.mean():>8.1f}  {flag}")
        out["peak"] = {k: {kk: vv for kk, vv in p.items() if kk != "third_octave_rel"} for k, (_, _, p) in rows.items() if p}
        out["third_octave_diff"] = bands

    if a.excerpts:
        os.makedirs(a.excerpts, exist_ok=True)
        for k, (au, an, _) in rows.items():
            if not an["peak_bars"]:
                continue
            seg = SE.excerpt(au.x, au.sr, an["bpm"], an["peak_bars"])
            seg = seg * 10 ** ((a.target - L.integrated(seg, au.sr)) / 20)
            path = os.path.join(a.excerpts, f"{k.replace('TARGET ', '')} - peak {an['peak_bars'][0]}-{an['peak_bars'][1]} - {a.target:g}LUFS.wav")
            sf.write(path, seg, au.sr, subtype="PCM_24")
        print(f"\nlevel-matched peak excerpts -> {a.excerpts}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


def cmd_review(a):
    from . import review
    path, fb = review.run(a.file, a.refs, a.bpm, codecs=not a.no_codecs)
    print("\n".join("- " + x for x in fb) or "nothing flagged")
    print(f"(full review: {os.path.relpath(path, LAB)})")




def cmd_calibrate(a):
    sys.path.insert(0, os.path.join(LAB, "calibration"))
    import checks  # noqa
    ok = checks.write_report(os.path.join(LAB, "calibration", "CALIBRATION.md"), crosscheck=not a.quick)
    sys.exit(0 if ok else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="mlab", description="Calibrated mastering instruments (HW002 lab)")
    sp = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args, **kw):
        s = sp.add_parser(name, help=kw.pop("help", None))
        for arg in args:
            s.add_argument(*arg[0], **arg[1])
        s.set_defaults(fn=fn)
        return s

    F = (["file"], {})
    J = (["--json"], {"action": "store_true"})
    add("measure", cmd_measure, F, J, (["--codecs"], {"action": "store_true"}), help="full measurement sheet")
    add("premaster", cmd_premaster, F, J, help="Ch.14 premaster checklist")
    add("deliver", cmd_deliver, F, J, (["--no-codecs"], {"action": "store_true"}), help="platform normalization + codec round-trip")
    add("bitdepth", cmd_bitdepth, F, help="word length / dither forensics")
    add("spectrum", cmd_spectrum, F, (["--ref"], {}), (["--phon"], {"type": float}),
        (["--ref-phon"], {"type": float, "default": 83.0}), help="tonal balance, optional vs reference")
    add("eq-diff", cmd_eqdiff, (["dry"], {}), (["wet"], {}), J, help="EQ curve a device applied")
    add("comp-probe", cmd_compprobe, (["dry"], {}), (["wet"], {}), help="estimate compressor settings from a probe render")
    add("probe", cmd_probe, (["--sr"], {"type": int, "default": 44100}), help="write comp/eq probe signals")
    add("match", cmd_match, (["files"], {"nargs": "+"}), (["--target"], {"type": float}), help="loudness-match files")
    add("abx", cmd_abx, (["a"], {}), (["b"], {}), (["--trials"], {"type": int, "default": 12}),
        (["--start"], {"type": float}), (["--dur"], {"type": float}), (["--out"], {}), help="blind ABX kit")
    add("abx-score", cmd_abxscore, (["folder"], {}), (["answers"], {}), help="score ABX answers")
    add("kcal", cmd_kcal, (["--sr"], {"type": int, "default": 44100}), help="K-System calibration noise")
    add("als", cmd_als, F, J, help="inspect an Ableton set")
    add("review", cmd_review, F, (["--refs"], {"default": os.path.join(LAB, "audio", "refs")}),
        (["--bpm"], {"type": float, "default": 160.0}), (["--no-codecs"], {"action": "store_true"}),
        help="one-shot premaster review with feedback")
    add("refs", cmd_refs, F, (["refs"], {}),
        (["--peaks"], {"action": "store_true", "help": "structure + peak window vs peak window"}),
        (["--excerpts"], {"help": "with --peaks: write level-matched peak excerpts here"}),
        (["--target"], {"type": float, "default": -14.0, "help": "excerpt loudness (LUFS)"}),
        (["--json"], {"help": "with --peaks: write results to this JSON file"}),
        help="compare with a folder of references")
    add("calibrate", cmd_calibrate, (["--quick"], {"action": "store_true"}), help="run known-answer checks")
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
