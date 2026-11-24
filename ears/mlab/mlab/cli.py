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
        print(f"  [{row['status']:4}] {row['check']:30} {row['value']!s:>10}   {row['why']}")


def cmd_deliver(a):
    from . import delivery

    au = aio.load(a.file)
    res = delivery.report(au.x, au.sr, codecs=not a.no_codecs)
    if a.json:
        return _out(res, True)
    print(f"Delivery: {os.path.basename(a.file)}  I={res['integrated']} LUFS  TP={res['true_peak']} dBTP\n")
    for p, v in res["normalization"].items():
        print(
            f"  {p:13} gain {v['gain_db']!s:>6} dB -> {v['playback_lufs']!s:>6} LUFS, {v['playback_true_peak']!s:>6} dBTP   ({v['note']})"
        )
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
    out = {
        "slope_db_per_oct": tb["slope_db_per_oct"],
        "groups": tb["groups_db_rel_total"],
        "stereo": S.stereo_by_band(au.x, au.sr),
    }
    if a.ref:
        rf = aio.load(a.ref)
        out["difference_vs_ref_third_octave"] = S.compare(au.x, rf.x, au.sr, rf.sr)
    if a.phon is not None:
        out[f"perceived_change_vs_{a.ref_phon}_phon"] = S.perceived_balance(tb["third_octave"], a.phon, a.ref_phon)
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
    from . import dynamics as D

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
    print(
        f"wrote probes to {os.path.relpath(out, LAB)}/ (drag into Live, render through the device, export 32-bit float)"
    )


def cmd_match(a):
    from . import compare

    auds = [aio.load(p) for p in a.files]
    res, tgt = compare.match(auds, a.target)
    out = os.path.join(LAB, "audio", "renders", "matched")
    for au, (x, g) in zip(auds, res, strict=True):
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
    print(
        "Main chain: "
        + (", ".join(f"{d['device']}{'' if d['on'] else ' (off)'}" for d in s["main_devices"]) or "(empty)")
    )
    for t in s["tracks"]:
        devs = ", ".join(f"{d['device']}{'' if d['on'] else ' (off)'}" for d in t["devices"])
        print(
            f"  {t['type'][:5]:5} {t['name'][:40]:40} {t['volume_db']!s:>7} dB {'' if t['active'] else '[deactivated]'}  {devs}"
        )
    for f in s["findings"]:
        print("  ! " + f)


def _ref_paths(folder):
    return [
        p
        for p in sorted(glob.glob(os.path.join(folder, "*")))
        if os.path.splitext(p)[1].lower() in (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a")
    ]


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
        print(
            f"{k:<19}{an['bpm']:>7.2f}{an['bars']:>6}  {an['main_break']!s:<12}{an['peak_bars']!s:<12}"
            f"{an['drop_vs_peak_high_db'] if an['drop_vs_peak_high_db'] is not None else '-':>13}  {an['peak_after_main_break']}"
        )

    tp = tgt[2]
    rp = {k: v[2] for k, v in refs.items() if v[2]}
    if tp and rp:
        print("\nPeak window, level-independent\n")
        print(f"{'track':<19}{'LUFS':>7}{'crest':>7}{'corr<120':>10}{'S-M<120':>9}")
        for k, (_, _, p) in rows.items():
            if p:
                print(
                    f"{k:<19}{p['lufs']:>7.2f}{p['crest_median_db']:>7.2f}{p['low_corr']:>10.3f}{p['low_side_minus_mid_db']:>9.1f}"
                )
        fc = [c for c, _ in tp["third_octave_rel"]]
        tv = np.array([v for _, v in tp["third_octave_rel"]])
        R = np.array([[v for _, v in p["third_octave_rel"][: len(fc)]] for p in rp.values()])
        d = tv[None, : R.shape[1]] - R
        print("\nTarget minus each reference, 1/3 octave, equal total energy (dB)\n")
        print(f"{'Hz':>7}" + "".join(f"{k[:9]:>10}" for k in rp) + f"{'mean':>8}  flag")
        bands = []
        for i in range(d.shape[1]):
            col = d[:, i]
            flag = "below all" if col.max() < -2 else "above all" if col.min() > 2 else ""
            bands.append(
                {
                    "hz": fc[i],
                    "diff": [round(float(v), 2) for v in col],
                    "mean": round(float(col.mean()), 2),
                    "flag": flag,
                }
            )
            print(f"{fc[i]:>7.0f}" + "".join(f"{v:>10.1f}" for v in col) + f"{col.mean():>8.1f}  {flag}")
        out["peak"] = {
            k: {kk: vv for kk, vv in p.items() if kk != "third_octave_rel"} for k, (_, _, p) in rows.items() if p
        }
        out["third_octave_diff"] = bands

    if a.excerpts:
        os.makedirs(a.excerpts, exist_ok=True)
        for k, (au, an, _) in rows.items():
            if not an["peak_bars"]:
                continue
            seg = SE.excerpt(au.x, au.sr, an["bpm"], an["peak_bars"])
            seg = seg * 10 ** ((a.target - L.integrated(seg, au.sr)) / 20)
            path = os.path.join(
                a.excerpts,
                f"{k.replace('TARGET ', '')} - peak {an['peak_bars'][0]}-{an['peak_bars'][1]} - {a.target:g}LUFS.wav",
            )
            sf.write(path, seg, au.sr, subtype="PCM_24")
        print(f"\nlevel-matched peak excerpts -> {a.excerpts}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


def _num(v, fmt="{:+.1f}", none="-"):
    if v is None:
        return none
    s = fmt.format(v)
    return fmt.format(0.0) if not s.lstrip("+-").replace("0", "").replace(".", "") else s  # no "-0.0"


def _refs_text(n):
    return f"{n} reference" + ("" if n == 1 else "s")


def _range_row(label, g, fmt="{:.1f}", width=26):
    """label | mix | refs mean [min .. max] | diff | outside (g from target.gap)."""
    if not g:
        return f"  {label:<{width}}{'-':>8}"
    rng = f"{fmt.format(g['mean'])} [{fmt.format(g['min'])} .. {fmt.format(g['max'])}]"
    flag = "  <" if g["outside"] < 0 else ("  >" if g["outside"] > 0 else "")
    return f"  {label:<{width}}{fmt.format(g['mix']):>8}   {rng:<24}{_num(g['diff']):>7}{_num(g['outside']):>9}{flag}"


def _ref_profiles(a):
    from . import target as T

    refs = T.load_refs(a.refs, a.set)
    if not refs:
        sys.exit(f"no references in {a.refs}" + (f" with set {a.set!r}" if a.set else ""))
    return refs, {r["id"]: T.profile_ref(r) for r in refs}


def cmd_target(a):
    from . import target as T

    au = aio.load(a.file)
    wins = T.windows(a.drop, a.bar)
    mix = T.profile(au.x, au.sr, wins, a.bar)
    refs, profs = _ref_profiles(a)
    g = T.gaps(mix, profs)
    print(
        f"{os.path.basename(a.file)} ({au.sr / 1000:g} kHz) vs {_refs_text(len(refs))}"
        + (f", set {a.set}" if a.set else "")
        + f"; drop {a.drop:g} s, bar {a.bar:g} s"
    )
    for r_ in refs:
        p = profs[r_["id"]]
        spans = ", ".join(f"{w} {v['span_s'][0]:.1f}-{v['span_s'][1]:.1f} s" for w, v in p["windows"].items())
        print(f"  ref {r_['id'][:40]:<40} {p['sr'] / 1000:g} kHz  {spans}")
    for w, why in mix["skipped"].items():
        print(f"  mix window {w} skipped: {why}")
    head = f"  {'':<26}{'mix':>8}   {'refs mean [min .. max]':<24}{'diff':>7}{'outside':>9}"
    print("\nSection contrast, LUFS(drop) - LUFS(build), LU")
    print(head)
    print(_range_row("contrast", g["contrast_lu"]))
    for w, gw in g["windows"].items():
        a0, b0 = mix["windows"][w]["span_s"]
        print(f"\n== {w.upper()} {a0:.1f}-{b0:.1f} s, {gw['n_refs']} refs ==")
        print(head)
        sc = gw["scalars"]
        for key, label in (
            ("lufs", "LUFS"),
            ("plr_db", "PLR (dB, true peak)"),
            ("block_crest_median_db", "block crest (dB)"),
            ("transient_contrast_median_db", "punch (dB)"),
        ):
            print(_range_row(label, sc[key]))
        print("\n  Regions (dB rel LUFS)")
        for k in T.REGION_KEYS:
            print(_range_row(T.LABELS[k], gw["regions"][k]))
        print("\n  Side minus mid (dB)")
        for k in T.SM_KEYS:
            print(_range_row(T.LABELS[k], gw["side_minus_mid_db"][k]))
        print("\n  1/3 octave, mix - refs mean (dB); < or > = outside the refs' range")
        cells = [
            f"{T.nominal(b['hz'])}:{b['diff']:+.1f}{'<' if b['outside'] < 0 else '>' if b['outside'] > 0 else ''}"
            for b in gw["bands"]
        ]
        for i in range(0, len(cells), 10):
            print("  " + " ".join(f"{c:<11}" for c in cells[i : i + 10]).rstrip())
        s = gw["score"]
        print(
            f"  score {T.hz_text(T.SCORE_HZ[0])}-{T.hz_text(T.SCORE_HZ[1])}: rms outside "
            f"{_num(s['rms_outside_db'], '{:.2f}')} dB, rms diff {_num(s['rms_diff_db'], '{:.2f}')} dB "
            f"({s['bands']} bands)"
        )
    if a.json:
        aio.dump_json(
            {
                "file": a.file,
                "drop_s": a.drop,
                "bar_s": a.bar,
                "set": a.set,
                "mix": mix,
                "refs": [{k: r_[k] for k in ("id", "title", "drop", "bar_s", "set") if k in r_} for r_ in refs],
                "ref_profiles": profs,
                "gaps": g,
            },
            a.json,
        )
        print(f"\n(saved {a.json})")


def cmd_eqfit(a):
    from . import eqfit as E
    from . import target as T

    names = a.names or [_stem(p) for p in a.stems]
    if len(names) != len(a.stems) or len(set(names)) != len(names):
        sys.exit("--names needs one unique name per stem")
    auds = [aio.load(p) for p in a.stems]
    if len({au.sr for au in auds}) > 1:
        sys.exit("stems must share one sample rate, got " + ", ".join(str(au.sr) for au in auds))
    sr = auds[0].sr
    with open(a.moves) as fh:
        spec = json.load(fh)
    opts = {k: spec[k] for k in ("weights", "alpha", "beta") if "moves" in spec and k in spec}
    moves = spec.get("moves", spec)
    refs, profs = _ref_profiles(a)
    wins = T.windows(a.drop, a.bar)
    res = E.fit(
        {n: au.x for n, au in zip(names, auds, strict=True)}, sr, wins, T.ref_stats(profs), moves, bar_s=a.bar, **opts
    )
    ob = res["objective"]
    print(
        f"eqfit: {len(names)} stems ({', '.join(names)}) at {sr / 1000:g} kHz vs {_refs_text(len(refs))}"
        + (f", set {a.set}" if a.set else "")
        + f"; drop {a.drop:g} s, bar {a.bar:g} s"
    )
    print(
        f"objective {ob['before']:.2f} with no moves -> {_num(ob['after'], '{:.2f}')}"
        f" (alpha {ob['alpha']:g}, beta {ob['beta']:g}, weights {ob['weights']}, best of {len(res['starts'])} starts)"
    )
    if not res["converged"]:
        best = min(res["starts"], key=lambda r_: r_["objective"])
        print(f"  ! the best start did not converge ({best['message']}); the plan may not be final")
    for w, u in res["unreachable"].items():
        print(
            f"  {w}: left out of the fit, no content to EQ (>{E.UNREACHABLE_DB:g} dB under every reference): "
            + ", ".join(T.hz_text(b["hz"]) for b in u)
        )
    if res["trimmed_s"] > 0:
        print(f"  stems trimmed to the shortest: {res['trimmed_s']:.2f} s cut")
    for w, why in res["skipped"].items():
        print(f"  window {w} skipped: {why}")
    print(f"\nFitted values\n  {'stem':<12}{'parameter':<16}{'kind':<11}{'value':>10}   bounds")
    for p in res["params"]:
        f_ = p["param"].endswith(".f")
        val = (
            f"{p['value']:.0f} Hz"
            if f_
            else (_num(p["value"], "{:.2f}") if p["param"].endswith(".q") else _num(p["value"], "{:+.2f}") + " dB")
        )
        print(f"  {p['stem']:<12}{p['param']:<16}{p['kind']:<11}{val:>10}   [{p['bounds'][0]:g}, {p['bounds'][1]:g}]")
    print("\nPlan")
    for stem, sp in res["plan"].items():
        eqs = "; ".join(
            f"{b['kind']} {b['f']:.0f} Hz"
            + (f" {b['gain_db']:+.1f} dB" if b["kind"] in E.GAINED else "")
            + f" Q {b['q']:.2f}"
            for b in sp["eq"]
        )
        print(f"  {stem}: fader {_num(sp['gain_db'])} dB" + (f"; {eqs}" if eqs else ""))
    for w, rw in res["windows"].items():
        print(f"\n== {w.upper()}: predicted LUFS change {rw['lufs_change_lu']:+.2f} LU ==")
        print(
            f"  {'region (dB rel LUFS)':<26}{'before':>8}{'after':>8}   {'refs mean [min .. max]':<24}{'outside before -> after':>24}"
        )
        for k in T.REGION_KEYS:
            b0, a0 = rw["before"]["regions"][k], rw["after"]["regions"][k]
            if not b0:
                continue
            rng = f"{b0['mean']:.1f} [{b0['min']:.1f} .. {b0['max']:.1f}]"
            print(
                f"  {T.LABELS[k]:<26}{b0['mix']:>8.1f}{a0['mix']:>8.1f}   {rng:<24}"
                f"{_num(b0['outside']):>15} -> {_num(a0['outside'])}"
            )
        sb, sa = rw["before"]["score"], rw["after"]["score"]
        print(
            f"  score 31.5 Hz-16 kHz: rms outside {_num(sb['rms_outside_db'], '{:.2f}')} -> "
            f"{_num(sa['rms_outside_db'], '{:.2f}')} dB, rms diff {_num(sb['rms_diff_db'], '{:.2f}')} -> "
            f"{_num(sa['rms_diff_db'], '{:.2f}')} dB ({sa['bands']} bands)"
        )
    print("\nModel check: predicted with no moves vs measured stem sum, 31.5 Hz-16 kHz")
    for w, m in res["model_check"].items():
        print(
            f"  {w}: max |error| {m['max_abs_err_db']:.2f} dB at {T.hz_text(m['at_hz'])} (rms {m['rms_err_db']:.2f} dB)"
        )
    print("  " + res["note"])
    if any(m["max_abs_err_db"] > 1.0 for m in res["model_check"].values()):
        print(
            "  ! model error above 1 dB: the stems' powers do not add up to their sum there;"
            " treat predicted moves in those bands with care"
        )
    if res.get("measured"):
        print("\nMeasured check: the plan applied to the stems (dsp.eq), EQ'd sum measured")
        for w, m in res["measured"].items():
            print(
                f"  {w}: LUFS change measured {m['lufs_change_measured_lu']:+.2f} LU, predicted "
                f"{m['lufs_change_predicted_lu']:+.2f} LU; worst band error {m['max_abs_band_err_db']:.2f} dB"
                + (f" at {T.hz_text(m['at_hz'])}" if m["at_hz"] else "")
                + ("  ! LUFS prediction off by more than 0.5 LU: the band targets moved too" if m["flag"] else "")
            )
    if a.out:
        aio.dump_json(
            {
                "stems": dict(zip(names, a.stems, strict=True)),
                "moves": moves,
                "drop_s": a.drop,
                "bar_s": a.bar,
                "refs": [r_["id"] for r_ in refs],
                "set": a.set,
                **res,
            },
            a.out,
        )
        print(f"\n(saved {a.out})")


def cmd_review(a):
    from . import review

    path, fb = review.run(a.file, a.refs, a.bpm, codecs=not a.no_codecs)
    print("\n".join("- " + x for x in fb) or "nothing flagged")
    print(f"(full review: {os.path.relpath(path, LAB)})")


def cmd_hyp(a):
    from . import hypothesis

    outdir, verdict = hypothesis.run(a.file, codecs=a.codecs)
    print(f"{verdict}  →  {outdir}")


def cmd_calibrate(a):
    sys.path.insert(0, os.path.join(LAB, "calibration"))
    import checks

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
    add(
        "deliver",
        cmd_deliver,
        F,
        J,
        (["--no-codecs"], {"action": "store_true"}),
        help="platform normalization + codec round-trip",
    )
    add("bitdepth", cmd_bitdepth, F, help="word length / dither forensics")
    add(
        "spectrum",
        cmd_spectrum,
        F,
        (["--ref"], {}),
        (["--phon"], {"type": float}),
        (["--ref-phon"], {"type": float, "default": 83.0}),
        help="tonal balance, optional vs reference",
    )
    add("eq-diff", cmd_eqdiff, (["dry"], {}), (["wet"], {}), J, help="EQ curve a device applied")
    add(
        "comp-probe",
        cmd_compprobe,
        (["dry"], {}),
        (["wet"], {}),
        help="estimate compressor settings from a probe render",
    )
    add("probe", cmd_probe, (["--sr"], {"type": int, "default": 44100}), help="write comp/eq probe signals")
    add("match", cmd_match, (["files"], {"nargs": "+"}), (["--target"], {"type": float}), help="loudness-match files")
    add(
        "abx",
        cmd_abx,
        (["a"], {}),
        (["b"], {}),
        (["--trials"], {"type": int, "default": 12}),
        (["--start"], {"type": float}),
        (["--dur"], {"type": float}),
        (["--out"], {}),
        help="blind ABX kit",
    )
    add("abx-score", cmd_abxscore, (["folder"], {}), (["answers"], {}), help="score ABX answers")
    add("kcal", cmd_kcal, (["--sr"], {"type": int, "default": 44100}), help="K-System calibration noise")
    add("als", cmd_als, F, J, help="inspect an Ableton set")
    add(
        "review",
        cmd_review,
        F,
        (["--refs"], {"default": os.path.join(LAB, "audio", "refs")}),
        (["--bpm"], {"type": float, "default": 160.0}),
        (["--no-codecs"], {"action": "store_true"}),
        help="one-shot premaster review with feedback",
    )
    add(
        "refs",
        cmd_refs,
        F,
        (["refs"], {}),
        (["--peaks"], {"action": "store_true", "help": "structure + peak window vs peak window"}),
        (["--excerpts"], {"help": "with --peaks: write level-matched peak excerpts here"}),
        (["--target"], {"type": float, "default": -14.0, "help": "excerpt loudness (LUFS)"}),
        (["--json"], {"help": "with --peaks: write results to this JSON file"}),
        help="compare with a folder of references",
    )
    R = (["--refs"], {"required": True, "help": "refs.json: {refs: [{id, file, drop, barSeconds, set}]}"})
    SET = (["--set"], {"help": "only references whose set is this (e.g. hw002)"})
    DROP = (["--drop"], {"type": float, "default": 24.0, "help": "drop time of the mix in seconds (default 24)"})
    BAR = (["--bar"], {"type": float, "default": 1.5, "help": "bar length in seconds (default 1.5 = 160 BPM)"})
    add(
        "target",
        cmd_target,
        F,
        R,
        SET,
        DROP,
        BAR,
        (["--json"], {"help": "write profiles and gaps to this JSON file"}),
        help="mix vs references per window (build, drop): bands, regions, side/mid, PLR, contrast",
    )
    add(
        "eqfit",
        cmd_eqfit,
        (["--stems"], {"nargs": "+", "required": True}),
        (["--names"], {"nargs": "+", "help": "one name per stem (default: file names)"}),
        (["--moves"], {"required": True, "help": "moves JSON: {stem: [EQ bands] or {eq, gain_db}}"}),
        R,
        SET,
        DROP,
        BAR,
        (["--out"], {"help": "write the plan and predictions to this JSON file"}),
        help="fit EQ moves on stems so their sum matches the references",
    )
    add(
        "hyp",
        cmd_hyp,
        (["action"], {"choices": ["run"]}),
        F,
        (
            ["--codecs"],
            {
                "action": argparse.BooleanOptionalAction,
                "help": "also measure after codec round trips (overrides the YAML's codecs)",
            },
        ),
        help="run a hypothesis YAML",
    )
    add("calibrate", cmd_calibrate, (["--quick"], {"action": "store_true"}), help="run known-answer checks")
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
