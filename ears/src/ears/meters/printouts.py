"""What `mlab target`, `mlab eqfit` and `mlab refs --peaks` print: pure functions from results to lines of text.

The CLI (cli.py) loads files, runs the instruments, prints these lines and writes the files; nothing here reads or
writes anything, so each report can be checked from a result alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from . import bands as B
from . import eqfit as E

RANGE_HEAD = f"  {'':<26}{'mix':>8}   {'refs mean [min .. max]':<24}{'diff':>7}{'outside':>9}"
TARGET_SCALARS = (
    ("lufs", "LUFS"),
    ("plr_db", "PLR (dB, true peak)"),
    ("block_crest_median_db", "block crest (dB)"),
    ("transient_contrast_median_db", "punch (dB)"),
)


def number(v: float | None, fmt: str = "{:+.1f}", none: str = "-") -> str:
    """v formatted, or `none` for None; never "-0.0"."""
    if v is None:
        return none
    s = fmt.format(v)
    return fmt.format(0.0) if not s.lstrip("+-").replace("0", "").replace(".", "") else s


def refs_text(n: int) -> str:
    return f"{n} reference" + ("" if n == 1 else "s")


def range_row(label: str, g: Mapping[str, Any] | None, fmt: str = "{:.1f}", width: int = 26) -> str:
    """label | mix | refs mean [min .. max] | diff | outside (g from target.gap)."""
    if not g:
        return f"  {label:<{width}}{'-':>8}"
    rng = f"{fmt.format(g['mean'])} [{fmt.format(g['min'])} .. {fmt.format(g['max'])}]"
    flag = "  <" if g["outside"] < 0 else ("  >" if g["outside"] > 0 else "")
    return (
        f"  {label:<{width}}{fmt.format(g['mix']):>8}   {rng:<24}{number(g['diff']):>7}{number(g['outside']):>9}{flag}"
    )


def _header(subject: str, n_refs: int, set_name: str | None, drop_s: float, bar_s: float) -> str:
    return (
        f"{subject} vs {refs_text(n_refs)}"
        + (f", set {set_name}" if set_name else "")
        + f"; drop {drop_s:g} s, bar {bar_s:g} s"
    )


# ------------------------------------------------------------------ target
def target_report(
    file_name: str,
    sr: int,
    refs: Sequence[Mapping[str, Any]],
    ref_profiles: Mapping[str, Mapping[str, Any]],
    mix: Mapping[str, Any],
    gaps: Mapping[str, Any],
    set_name: str | None,
    drop_s: float,
    bar_s: float,
) -> list[str]:
    """`mlab target`: the references used, the section contrast, then per window its scalars, regions, side minus
    mid and 1/3-octave differences, each against the references' mean and range."""
    out = [_header(f"{file_name} ({sr / 1000:g} kHz)", len(refs), set_name, drop_s, bar_s)]
    for ref in refs:
        p = ref_profiles[ref["id"]]
        spans = ", ".join(f"{w} {v['span_s'][0]:.1f}-{v['span_s'][1]:.1f} s" for w, v in p["windows"].items())
        out.append(f"  ref {ref['id'][:40]:<40} {p['sr'] / 1000:g} kHz  {spans}")
    for w, why in mix["skipped"].items():
        out.append(f"  mix window {w} skipped: {why}")
    out += ["\nSection contrast, LUFS(drop) - LUFS(build), LU", RANGE_HEAD, range_row("contrast", gaps["contrast_lu"])]
    for w, gw in gaps["windows"].items():
        out += _target_window(w, gw, mix["windows"][w]["span_s"])
    return out


def _target_window(name: str, gw: Mapping[str, Any], span: Sequence[float]) -> list[str]:
    out = [f"\n== {name.upper()} {span[0]:.1f}-{span[1]:.1f} s, {gw['n_refs']} refs ==", RANGE_HEAD]
    out += [range_row(label, gw["scalars"][key]) for key, label in TARGET_SCALARS]
    out.append("\n  Regions (dB rel LUFS)")
    out += [range_row(B.REGION_LABELS[k], gw["regions"][k]) for k in B.REGION_KEYS]
    out.append("\n  Side minus mid (dB)")
    out += [range_row(B.REGION_LABELS[k], gw["side_minus_mid_db"][k]) for k in B.SIDE_MID_KEYS]
    out.append("\n  1/3 octave, mix - refs mean (dB); < or > = outside the refs' range")
    cells = [
        f"{B.nominal(b['hz'])}:{b['diff']:+.1f}{'<' if b['outside'] < 0 else '>' if b['outside'] > 0 else ''}"
        for b in gw["bands"]
    ]
    out += ["  " + " ".join(f"{c:<11}" for c in cells[i : i + 10]).rstrip() for i in range(0, len(cells), 10)]
    s = gw["score"]
    out.append(
        f"  score {B.hz_text(B.SCORE_HZ[0])}-{B.hz_text(B.SCORE_HZ[1])}: rms outside "
        f"{number(s['rms_outside_db'], '{:.2f}')} dB, rms diff {number(s['rms_diff_db'], '{:.2f}')} dB "
        f"({s['bands']} bands)"
    )
    return out


# ------------------------------------------------------------------ eqfit
def eqfit_report(
    names: Sequence[str],
    sr: int,
    n_refs: int,
    set_name: str | None,
    drop_s: float,
    bar_s: float,
    res: Mapping[str, Any],
) -> list[str]:
    """`mlab eqfit`: the fit's objective and warnings, the fitted values, the plan, the regions before and after per
    window, the model check and the measured check."""
    ob = res["objective"]
    out = [
        _header(
            f"eqfit: {len(names)} stems ({', '.join(names)}) at {sr / 1000:g} kHz", n_refs, set_name, drop_s, bar_s
        ),
        f"objective {ob['before']:.2f} with no moves -> {number(ob['after'], '{:.2f}')}"
        f" (alpha {ob['alpha']:g}, beta {ob['beta']:g}, weights {ob['weights']}, best of {len(res['starts'])} starts)",
    ]
    if not res["converged"]:
        best = min(res["starts"], key=lambda r_: r_["objective"])
        out.append(f"  ! the best start did not converge ({best['message']}); the plan may not be final")
    for w, u in res["unreachable"].items():
        out.append(
            f"  {w}: left out of the fit, no content to EQ (>{E.UNREACHABLE_DB:g} dB under every reference): "
            + ", ".join(B.hz_text(b["hz"]) for b in u)
        )
    if res["trimmed_s"] > 0:
        out.append(f"  stems trimmed to the shortest: {res['trimmed_s']:.2f} s cut")
    out += [f"  window {w} skipped: {why}" for w, why in res["skipped"].items()]
    out.append(f"\nFitted values\n  {'stem':<12}{'parameter':<16}{'kind':<11}{'value':>10}   bounds")
    out += [_fitted_value(p) for p in res["params"]]
    out.append("\nPlan")
    out += [_plan_line(stem, sp) for stem, sp in res["plan"].items()]
    for w, rw in res["windows"].items():
        out += _eqfit_window(w, rw)
    out += _model_check(res)
    if res.get("measured"):
        out.append("\nMeasured check: the plan applied to the stems (dsp.eq), EQ'd sum measured")
        out += [_measured_line(w, m) for w, m in res["measured"].items()]
    return out


def _fitted_value(p: Mapping[str, Any]) -> str:
    if p["param"].endswith(".f"):
        val = f"{p['value']:.0f} Hz"
    elif p["param"].endswith(".q"):
        val = number(p["value"], "{:.2f}")
    else:
        val = number(p["value"], "{:+.2f}") + " dB"
    return f"  {p['stem']:<12}{p['param']:<16}{p['kind']:<11}{val:>10}   [{p['bounds'][0]:g}, {p['bounds'][1]:g}]"


def _plan_line(stem: str, sp: Mapping[str, Any]) -> str:
    eqs = "; ".join(
        f"{b['kind']} {b['f']:.0f} Hz"
        + (f" {b['gain_db']:+.1f} dB" if b["kind"] in E.GAINED else "")
        + f" Q {b['q']:.2f}"
        for b in sp["eq"]
    )
    return f"  {stem}: fader {number(sp['gain_db'])} dB" + (f"; {eqs}" if eqs else "")


def _eqfit_window(name: str, rw: Mapping[str, Any]) -> list[str]:
    out = [
        f"\n== {name.upper()}: predicted LUFS change {rw['lufs_change_lu']:+.2f} LU ==",
        f"  {'region (dB rel LUFS)':<26}{'before':>8}{'after':>8}   {'refs mean [min .. max]':<24}{'outside before -> after':>24}",
    ]
    for k in B.REGION_KEYS:
        b0, a0 = rw["before"]["regions"][k], rw["after"]["regions"][k]
        if not b0:
            continue
        rng = f"{b0['mean']:.1f} [{b0['min']:.1f} .. {b0['max']:.1f}]"
        out.append(
            f"  {B.REGION_LABELS[k]:<26}{b0['mix']:>8.1f}{a0['mix']:>8.1f}   {rng:<24}"
            f"{number(b0['outside']):>15} -> {number(a0['outside'])}"
        )
    sb, sa = rw["before"]["score"], rw["after"]["score"]
    out.append(
        f"  score 31.5 Hz-16 kHz: rms outside {number(sb['rms_outside_db'], '{:.2f}')} -> "
        f"{number(sa['rms_outside_db'], '{:.2f}')} dB, rms diff {number(sb['rms_diff_db'], '{:.2f}')} -> "
        f"{number(sa['rms_diff_db'], '{:.2f}')} dB ({sa['bands']} bands)"
    )
    return out


def _model_check(res: Mapping[str, Any]) -> list[str]:
    out = ["\nModel check: predicted with no moves vs measured stem sum, 31.5 Hz-16 kHz"]
    out += [
        f"  {w}: max |error| {m['max_abs_err_db']:.2f} dB at {B.hz_text(m['at_hz'])} (rms {m['rms_err_db']:.2f} dB)"
        for w, m in res["model_check"].items()
    ]
    out.append("  " + res["note"])
    if any(m["max_abs_err_db"] > 1.0 for m in res["model_check"].values()):
        out.append(
            "  ! model error above 1 dB: the stems' powers do not add up to their sum there;"
            " treat predicted moves in those bands with care"
        )
    return out


def _measured_line(name: str, m: Mapping[str, Any]) -> str:
    return (
        f"  {name}: LUFS change measured {m['lufs_change_measured_lu']:+.2f} LU, predicted "
        f"{m['lufs_change_predicted_lu']:+.2f} LU; worst band error {m['max_abs_band_err_db']:.2f} dB"
        + (f" at {B.hz_text(m['at_hz'])}" if m["at_hz"] else "")
        + ("  ! LUFS prediction off by more than 0.5 LU: the band targets moved too" if m["flag"] else "")
    )


# ------------------------------------------------------------------ refs --peaks
Peaks = tuple[Mapping[str, Any], Mapping[str, Any] | None]  # sections.analyze() and its peak_profile() (None: no peak)


def peaks_report(target_name: str, target: Peaks, refs: Mapping[str, Peaks]) -> tuple[dict[str, Any], list[str]]:
    """`mlab refs --peaks`: each track's structure, then (when the target and some references have a peak window)
    the peak windows' level-independent measures and the target's 1/3-octave difference from each reference.
    Returns the JSON result and the printed lines."""
    rows = {target_name: target, **refs}
    result: dict[str, Any] = {"structure": {k: an for k, (an, _) in rows.items()}}
    out = [
        "Structure (bars, 1-based)\n",
        f"{'track':<19}{'BPM':>7}{'bars':>6}  {'main break':<12}{'peak':<12}{'drop vs peak':>13}  peak after break",
    ]
    for k, (an, _) in rows.items():
        drop = an["drop_vs_peak_high_db"] if an["drop_vs_peak_high_db"] is not None else "-"
        out.append(
            f"{k:<19}{an['bpm']:>7.2f}{an['bars']:>6}  {an['main_break']!s:<12}{an['peak_bars']!s:<12}"
            f"{drop:>13}  {an['peak_after_main_break']}"
        )
    target_peak = target[1]
    ref_peaks = {k: p for k, (_, p) in refs.items() if p}
    if not (target_peak and ref_peaks):
        return result, out
    out += ["\nPeak window, level-independent\n", f"{'track':<19}{'LUFS':>7}{'crest':>7}{'corr<120':>10}{'S-M<120':>9}"]
    for k, (_, p) in rows.items():
        if p:
            out.append(
                f"{k:<19}{p['lufs']:>7.2f}{p['crest_median_db']:>7.2f}{p['low_corr']:>10.3f}{p['low_side_minus_mid_db']:>9.1f}"
            )
    bands, lines = _third_octave_diff(target_peak, ref_peaks)
    out += lines
    result["peak"] = {
        k: {kk: vv for kk, vv in p.items() if kk != "third_octave_rel"} for k, (_, p) in rows.items() if p
    }
    result["third_octave_diff"] = bands
    return result, out


def _third_octave_diff(
    target_peak: Mapping[str, Any], ref_peaks: Mapping[str, Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    fc = [c for c, _ in target_peak["third_octave_rel"]]
    tv = np.array([v for _, v in target_peak["third_octave_rel"]])
    ref_levels = np.array([[v for _, v in p["third_octave_rel"][: len(fc)]] for p in ref_peaks.values()])
    d = tv[None, : ref_levels.shape[1]] - ref_levels
    out = [
        "\nTarget minus each reference, 1/3 octave, equal total energy (dB)\n",
        f"{'Hz':>7}" + "".join(f"{k[:9]:>10}" for k in ref_peaks) + f"{'mean':>8}  flag",
    ]
    bands = []
    for i in range(d.shape[1]):
        col = d[:, i]
        flag = "below all" if col.max() < -2 else "above all" if col.min() > 2 else ""
        bands.append(
            {"hz": fc[i], "diff": [round(float(v), 2) for v in col], "mean": round(float(col.mean()), 2), "flag": flag}
        )
        out.append(f"{fc[i]:>7.0f}" + "".join(f"{v:>10.1f}" for v in col) + f"{col.mean():>8.1f}  {flag}")
    return bands, out
