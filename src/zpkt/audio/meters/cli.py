"""Command line: python3 -m mlab <command> ...   (run from the lab root)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import io as aio
from . import lab, references
from . import windows as W
from .arrays import Json
from .io import Audio
from .references import Reference
from .util import r

LAB = lab.ROOT  # reports/ and audio/renders/ go here


def _out(obj: Any, as_json: bool) -> Any:
    if as_json:
        print(json.dumps(obj, indent=2, default=aio._json_default))
    return obj


def _stem(p: str) -> str:
    return Path(p).stem


def cmd_measure(a: argparse.Namespace) -> None:
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


def cmd_premaster(a: argparse.Namespace) -> None:
    from . import premaster

    res = premaster.run(aio.load(a.file))
    if a.json:
        _out(res, True)
        return
    print(f"Premaster check: {os.path.basename(a.file)} -> {res['overall']}\n")
    for row in res["checks"]:
        print(f"  [{row['status']:4}] {row['check']:30} {row['value']!s:>10}   {row['why']}")


def cmd_deliver(a: argparse.Namespace) -> None:
    from . import delivery

    au = aio.load(a.file)
    res = delivery.report(au.x, au.sr, codecs=not a.no_codecs)
    if a.json:
        _out(res, True)
        return
    print(f"Delivery: {os.path.basename(a.file)}  I={res['integrated']} LUFS  TP={res['true_peak']} dBTP\n")
    for p, v in res["normalization"].items():
        print(
            f"  {p:13} gain {v['gain_db']!s:>6} dB -> {v['playback_lufs']!s:>6} LUFS, {v['playback_true_peak']!s:>6} dBTP   ({v['note']})"
        )
    for c, v in res.get("codec_roundtrip", {}).items():
        print(f"  codec {c:8} {v}")
    for adv in res["advice"]:
        print("  ! " + adv)


def cmd_bitdepth(a: argparse.Namespace) -> None:
    from . import bitdepth

    _out(bitdepth.analyze(aio.load(a.file)), True)


def cmd_spectrum(a: argparse.Namespace) -> None:
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


def cmd_eqdiff(a: argparse.Namespace) -> None:
    from . import spectrum as S

    d, w = aio.load(a.dry), aio.load(a.wet)
    dd, ww, lag = S.align(d.x, w.x, sr=d.sr)
    res = S.eq_diff(dd, ww, d.sr)
    summ = S.summarize_eq(res)
    summ["latency_samples"] = lag
    if a.json:
        _out({"summary": summ, "curve": res}, True)
        return
    _out(summ, True)


def cmd_compprobe(a: argparse.Namespace) -> None:
    from . import dynamics as D

    d, w = aio.load(a.dry), aio.load(a.wet)
    dd, ww, lag = D.probe_align(d.x, w.x)
    res = D.comp_probe(dd, ww, d.sr)
    res["latency_samples"] = lag
    _out(res, True)


def cmd_probe(a: argparse.Namespace) -> None:
    from . import siggen

    out = os.path.join(LAB, "audio", "renders", "probes")
    x, lay = siggen.comp_probe(a.sr)
    aio.save(os.path.join(out, "comp_probe.wav"), x, a.sr, "PCM_24")
    aio.dump_json(lay, os.path.join(out, "comp_probe.layout.json"))
    aio.save(os.path.join(out, "eq_probe_pink.wav"), siggen.eq_probe(a.sr), a.sr, "PCM_24")
    print(
        f"wrote probes to {os.path.relpath(out, LAB)}/ (drag into Live, render through the device, export 32-bit float)"
    )


def cmd_match(a: argparse.Namespace) -> None:
    from . import compare

    auds = [aio.load(p) for p in a.files]
    res, tgt = compare.match(auds, a.target)
    out = os.path.join(LAB, "audio", "renders", "matched")
    for au, (x, g) in zip(auds, res, strict=True):
        p = os.path.join(out, f"{_stem(au.path)}_@{r(tgt, 1)}LUFS.wav")
        aio.save(p, x, au.sr)
        print(f"{os.path.basename(au.path)}: {r(g):+} dB -> {os.path.relpath(p, LAB)}")


def cmd_abx(a: argparse.Namespace) -> None:
    from . import compare

    out = a.out or os.path.join(LAB, "audio", "renders", "abx", f"{_stem(a.a)}_vs_{_stem(a.b)}")
    compare.abx_kit(aio.load(a.a), aio.load(a.b), out, a.trials, a.start, a.dur)
    print(f"ABX kit: {os.path.relpath(out, LAB)}  (see HOW_TO.md; do not open .answer_key.json)")


def cmd_abxscore(a: argparse.Namespace) -> None:
    from . import compare

    _out(compare.abx_score(a.folder, a.answers), True)


def cmd_kcal(a: argparse.Namespace) -> None:
    from . import siggen

    out = os.path.join(LAB, "audio", "renders", "k-system")
    for name, x in siggen.kcal_files(a.sr).items():
        aio.save(os.path.join(out, name), x, a.sr, "PCM_24")
    print(f"wrote K-System calibration noise to {os.path.relpath(out, LAB)}/ — see guides/ch20-21-monitoring.md")


def cmd_als(a: argparse.Namespace) -> None:
    from . import als

    s = als.read(a.file)
    if a.json:
        _out(s, True)
        return
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


def cmd_refs(a: argparse.Namespace) -> None:
    if a.peaks:
        _refs_peaks(a)
        return
    from . import compare, measure

    t = measure.flat(measure.sheet(aio.load(a.file)))
    refs = {
        references.reference_name(p, 18): measure.flat(measure.sheet(aio.load(p)))
        for p in references.reference_files(a.refs)
    }
    print(compare.refs_table(t, refs, measure.CORE_KEYS))


def _refs_peaks(a: argparse.Namespace) -> None:
    """Section-aware comparison: structure, then peak window against peak window."""
    import soundfile as sf

    from . import loudness as L
    from . import printouts
    from . import sections as SE

    def load(p: str) -> tuple[Audio, Json, Json | None]:
        au = aio.load(p)
        an = SE.analyze(au.x, au.sr)
        prof = SE.peak_profile(au.x, au.sr, an["bpm"], an["peak_bars"]) if an["peak_bars"] else None
        return au, an, prof

    target_name = "TARGET " + references.reference_name(a.file, 11)
    tgt = load(a.file)
    refs = {references.reference_name(p, 18): load(p) for p in references.reference_files(a.refs)}
    out, lines = printouts.peaks_report(target_name, tgt[1:], {k: v[1:] for k, v in refs.items()})
    print("\n".join(lines))
    if a.excerpts:
        Path(a.excerpts).mkdir(parents=True, exist_ok=True)
        for k, (au, an, _) in {target_name: tgt, **refs}.items():
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


def _ref_profiles(a: argparse.Namespace) -> tuple[list[Reference], dict[str, Json]]:
    from . import target as T

    refs = T.load_refs(a.refs, a.set)
    if not refs:
        sys.exit(f"no references in {a.refs}" + (f" with set {a.set!r}" if a.set else ""))
    return refs, {r["id"]: T.profile_ref(r) for r in refs}


def cmd_target(a: argparse.Namespace) -> None:
    from . import printouts
    from . import target as T

    au = aio.load(a.file)
    wins = W.windows(a.drop, a.bar)
    mix = T.profile(au.x, au.sr, wins, a.bar)
    refs, profs = _ref_profiles(a)
    g = T.gaps(mix, profs)
    lines = printouts.target_report(os.path.basename(a.file), au.sr, refs, profs, mix, g, a.set, a.drop, a.bar)
    print("\n".join(lines))
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


def cmd_eqfit(a: argparse.Namespace) -> None:
    from . import eqfit as E
    from . import printouts
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
    wins = W.windows(a.drop, a.bar)
    res = E.fit(
        {n: au.x for n, au in zip(names, auds, strict=True)}, sr, wins, T.ref_stats(profs), moves, bar_s=a.bar, **opts
    )
    print("\n".join(printouts.eqfit_report(names, sr, len(refs), a.set, a.drop, a.bar, res)))
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


def cmd_review(a: argparse.Namespace) -> None:
    from . import review

    path, fb = review.run(a.file, a.refs, a.bpm, codecs=not a.no_codecs, reports_dir=os.path.join(LAB, "reports"))
    print("\n".join("- " + x for x in fb) or "nothing flagged")
    print(f"(full review: {os.path.relpath(path, LAB)})")


def cmd_hyp(a: argparse.Namespace) -> None:
    from . import hypothesis

    outdir, verdict = hypothesis.run(a.file, codecs=a.codecs)
    print(f"{verdict}  →  {outdir}")


def cmd_calibrate(a: argparse.Namespace) -> None:
    sys.path.insert(0, os.path.join(LAB, "calibration"))
    import checks  # type: ignore[import-not-found]  # calibration/checks.py, put on the path above

    ok = checks.write_report(os.path.join(LAB, "calibration", "CALIBRATION.md"), crosscheck=not a.quick)
    sys.exit(0 if ok else 1)


def parser(prog: str = "mlab") -> argparse.ArgumentParser:
    """The argument parser: one subcommand per instrument. `ears` offers the same subcommands (ears/cli.py)."""
    p = argparse.ArgumentParser(prog=prog, description="Calibrated mastering instruments (HW002 lab)")
    sp = p.add_subparsers(dest="cmd", required=True)
    p.set_defaults(commands={})  # subcommand -> its help line, for commands()

    def add(
        name: str, fn: Callable[[argparse.Namespace], None], *args: tuple[list[str], dict[str, Any]], **kw: Any
    ) -> argparse.ArgumentParser:
        p.get_default("commands")[name] = kw.get("help") or ""
        s = sp.add_parser(name, help=kw.pop("help", None))
        for arg in args:
            s.add_argument(*arg[0], **arg[1])
        s.set_defaults(fn=fn)
        return s

    Arg = tuple[list[str], dict[str, Any]]
    F: Arg = (["file"], {})
    J: Arg = (["--json"], {"action": "store_true"})
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
    drop_help = f"drop time of the mix in seconds (default {W.DEFAULT_DROP_S:g})"
    bar_help = f"bar length in seconds (default {W.DEFAULT_BAR_S:g} = 160 BPM)"
    DROP = (["--drop"], {"type": float, "default": W.DEFAULT_DROP_S, "help": drop_help})
    BAR = (["--bar"], {"type": float, "default": W.DEFAULT_BAR_S, "help": bar_help})
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
    return p


def commands() -> dict[str, str]:
    """{subcommand: its one-line help}, in the order `mlab --help` lists them."""
    return dict(parser().get_default("commands"))


def main(argv: Sequence[str] | None = None, prog: str = "mlab") -> None:
    a = parser(prog).parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
