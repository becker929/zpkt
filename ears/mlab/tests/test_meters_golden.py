"""What every mlab instrument reports on fixed synthetic audio, pinned (see golden_check.py).

The calibration suite says the meters are right within a tolerance; these say they still report exactly what they
reported on 24 Nov 2026, so a refactor cannot move a number unnoticed.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from golden_check import check, text
from mlab import (
    als,
    bitdepth,
    compare,
    delivery,
    dsp,
    dynamics,
    hypothesis,
    measure,
    premaster,
    review,
    sections,
    siggen,
    target,
    util,
)
from mlab import io as aio
from mlab import loudness as L
from mlab import spectrum as S
from signals import SR, mix, reference, write

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration", "fixtures")


def fingerprint(y: np.ndarray) -> dict:
    """A few numbers that move if any sample of y moves."""
    y = np.asarray(y, dtype=float)
    flat = y.ravel()
    picks = np.linspace(0, flat.size - 1, 7).astype(int) if flat.size else []
    return {
        "shape": list(y.shape),
        "sum": float(flat.sum()),
        "sum_sq": float(np.dot(flat, flat)),
        "max_abs": float(np.max(np.abs(flat))) if flat.size else 0.0,
        "samples": [float(flat[i]) for i in picks],
    }


def test_loudness() -> None:
    x = mix()
    res = L.analyze(x, SR)
    check(
        "loudness",
        {
            "summary": res.summary(),
            "exact": {k: getattr(res, k) for k in ("integrated", "true_peak", "plr", "psr_min", "lra")},
            "momentary": res.momentary,
            "short_term": res.short_term,
            "integrated": L.integrated(x, SR),
            "true_peak_per_channel": L.true_peak_per_channel(x, SR),
            "sample_peak": L.sample_peak(x),
            "gain_to_-14": L.gain_to(x, SR, -14.0),
            "k_weighting_44100": [[b, a] for b, a in L.k_weighting(SR)],
            "oversample": [L.oversample_factor(sr) for sr in (44100, 96000, 192000)],
            "lra_of_short_term": L.loudness_range(res.short_term),
            "mono_file": L.analyze(x[:, :1], SR).summary(),
            "silence": L.analyze(np.zeros((SR, 2)), SR).summary(),
        },
    )


def test_dynamics() -> None:
    x = mix()
    probe, lay = siggen.comp_probe(SR)
    wet = dsp.compressor(probe, SR, -24, 3, 5, 120, 6, 2)
    check(
        "dynamics",
        {
            "analyze": dynamics.analyze(x, SR),
            "crest": dynamics.crest_db(x),
            "micro": dynamics.micro(x, SR),
            "transient_contrast": dynamics.transient_contrast(x, SR),
            "envelope": fingerprint(dynamics.envelope_db(x, SR, 1.0, 50.0)),
            "gain_curve": [fingerprint(v) for v in dynamics.gain_curve_db(probe, wet, SR)],
            "comp_probe": dynamics.comp_probe(probe, wet, SR, lay),
            "probe_align_lag": dynamics.probe_align(probe, np.vstack([np.zeros((300, 2)), wet]))[2],
        },
    )


def test_spectrum() -> None:
    x, ref = mix(), reference(3.0)
    eqd = dsp.eq(x, SR, [{"type": "peak", "f": 1000, "gain_db": 4, "q": 1.2}])
    dd, ww, lag = S.align(x, np.vstack([np.zeros((64, 2)), eqd]), sr=SR)
    curve = S.eq_diff(dd, ww, SR)
    tb = S.tonal_balance(x, SR)
    check(
        "spectrum",
        {
            "tonal_balance": tb,
            "third_octave": S.third_octave(x, SR),
            "centroid": S.centroid(x, SR),
            "stereo_by_band": S.stereo_by_band(x, SR),
            "compare_vs_ref": S.compare(x, ref, SR),
            "align_lag": lag,
            "eq_diff": curve,
            "summarize_eq": S.summarize_eq(curve),
            "iso226_60": S.iso226(60.0),
            "iso226_at": S.iso226(40.0, [31.5, 100.0, 1000.0, 8000.0]),
            "perceived_balance": S.perceived_balance(tb["third_octave"], 60.0, 83.0),
            "psd": fingerprint(S.psd(x, SR)[1]),
            "band_power": S.band_power(*S.psd(x, SR), 100.0, 200.0),
        },
    )


def test_bitdepth() -> None:
    x = mix() * util.lin(-6.0)
    q16 = dsp.quantize(x, 16, "tpdf", seed=2)
    rows = {}
    for name, y, subtype in (
        ("float", x, "FLOAT"),
        ("pcm16_tpdf", q16, "PCM_16"),
        ("pcm24_holding_16", q16, "PCM_24"),
        ("float_holding_24", dsp.quantize(x, 24), "FLOAT"),
        ("lossy", x, "lossy:mp3"),
        ("silence", np.zeros((SR, 2)), "PCM_24"),
    ):
        rows[name] = bitdepth.analyze(aio.Audio(y, SR, name, subtype, "WAV"))
    fade = (np.sin(2 * np.pi * 1000 * np.arange(SR * 3) / SR) * util.lin(np.linspace(-40, -96, SR * 3)))[:, None]
    rows["truncation_distortion"] = bitdepth.truncation_distortion(fade, dsp.truncate(fade, 16), SR, 1000)
    rows["floors"] = {
        f"{b}-{d}": bitdepth.theoretical_floor_dbfs(b, d) for b in (16, 24) for d in ("none", "rpdf", "tpdf")
    }
    rows["quiet_blocks"] = [fingerprint(v) if isinstance(v, np.ndarray) else v for v in bitdepth.quiet_blocks(q16, SR)]
    check("bitdepth", rows)


def test_read_int_codes(tmp_path) -> None:
    y = dsp.quantize(mix() * util.lin(-6.0), 16, "none")
    p16 = write(tmp_path / "x16.wav", y, subtype="PCM_16")
    p24 = write(tmp_path / "x24.wav", y, subtype="PCM_24")
    pf = write(tmp_path / "xf.wav", y)
    check(
        "read_int_codes",
        {
            "pcm16": fingerprint(bitdepth.read_int_codes(str(p16))),
            "pcm24": fingerprint(bitdepth.read_int_codes(str(p24))),
            "float": bitdepth.read_int_codes(str(pf)),
        },
    )


def test_premaster() -> None:
    x = mix() * util.lin(-8.0)
    clipped = x.copy()
    clipped[1000:1010] = 1.0
    check(
        "premaster",
        {
            "float_mix": premaster.run(aio.Audio(x, SR, "m", "FLOAT", "WAV")),
            "clipped_16bit": premaster.run(aio.Audio(clipped, SR, "c", "PCM_16", "WAV")),
            "mono": premaster.run(aio.Audio(x[:, :1], SR, "mono", "PCM_24", "WAV")),
            "lossy": premaster.run(aio.Audio(x, SR, "l", "lossy:mp3", "MP3")),
            "clip_runs": premaster.clip_runs(clipped),
        },
    )


def test_delivery() -> None:
    x = mix()
    check(
        "delivery",
        {
            "normalization_loud": delivery.normalization(-8.3, -0.4),
            "normalization_quiet": delivery.normalization(-19.0, -6.0),
            "normalization_silent": delivery.normalization(float("nan"), float("-inf")),
            "report": delivery.report(x, SR, codecs=False),
            "report_hot": delivery.report(x * util.lin(12.0), SR, codecs=False),
        },
    )


def test_sections() -> None:
    x, truth = siggen.song_sections(SR, 150.0)
    an = sections.analyze(x, SR)
    low, high = sections.bars(x, SR, an["bpm"])
    check(
        "sections",
        {
            "truth": truth,
            "analyze": an,
            "bars": [low, high],
            "peak_profile": sections.peak_profile(x, SR, an["bpm"], an["peak_bars"]),
            "rel_third_octave": sections._rel_third_octave(x[: SR * 4], SR),
            "onset_envelope": fingerprint(sections.onset_envelope(x[: SR * 4], SR)[0]),
            "kickless_runs": sections.kickless_runs([True, False, False, True, False, True, False, False, False]),
        },
    )


def test_target() -> None:
    x = mix()
    wins = target.windows(6.0, 0.375)
    prof = target.profile(x, SR, wins, 0.375)
    refs = {
        "bright": target.profile(reference(3.0), SR, wins, 0.375),
        "dark": target.profile(reference(-2.0), SR, wins, 0.375),
    }
    check(
        "target",
        {
            "windows": wins,
            "windows_layout": target.windows(24.0, 1.5, {"drop2": (16, 24), "build": None}),
            "profile": prof,
            "ref_stats": target.ref_stats(refs),
            "gaps": target.gaps(prof, refs),
            "nominal": [target.nominal(h) for h in (31.6, 1258.9, 20000.0, 440.0)],
            "hz_text": [target.hz_text(h) for h in (31.6, 1000.0, 16000.0)],
            "nperseg": [target.nperseg(sr) for sr in (44100, 48000, 96000)],
            "band_grid_48k": target.band_grid(48000),
            "region_edges_44k": target.region_edges(SR),
            "side_minus_mid_mono": target.side_minus_mid(x[:, 0], SR),
            "window_true_peak": target.window_true_peak(x, SR, 1000, 50000),
            "short_file": target.profile(x[: SR * 7], SR, wins, 0.375)["skipped"],
        },
    )


def test_load_refs(tmp_path) -> None:
    p = tmp_path / "refs.json"
    p.write_text(
        json.dumps(
            {
                "refs": [
                    {
                        "id": "a",
                        "title": "A",
                        "file": "a.flac",
                        "drop": 24,
                        "barSeconds": 1.5,
                        "bpm": 160,
                        "set": "hw002",
                    },
                    {"id": "b", "file": "b.wav", "drop": "20.5", "barSeconds": 1.6, "set": "other", "extra": 1},
                ]
            }
        )
    )
    got = target.load_refs(str(p), base_dir="/base")
    check("load_refs", {"all": got, "hw002": target.load_refs(str(p), "hw002", base_dir="/base")})


def test_measurement_sheet() -> None:
    au = aio.from_array(mix(), SR, "mix")
    sh = measure.sheet(au)
    check("measure_sheet", {"sheet": sh, "flat": measure.flat(sh), "core_keys": measure.CORE_KEYS})
    text("measure_sheet", measure.markdown(sh, "mix"))


def test_dsp() -> None:
    x = mix()
    y, gr = dsp.compressor(x, SR, -24, 4, 10, 100, 6, 3, return_gr=True)
    rms = dsp.compressor(x, SR, -30, 2, 20, 200, 0, 0, detector="rms")
    lim = dsp.limiter(x * util.lin(6), SR, -1.0)
    mastered, drive = dsp.master_to(x, SR, -12.0)
    check(
        "dsp",
        {
            "biquads": {
                k: dsp.biquad(k, 1000.0, SR, 3.0, 0.9) for k in ("peak", "lowshelf", "highshelf", "highpass", "lowpass")
            },
            "biquad_response": dsp.biquad_response_db("peak", 1000.0, SR, 6.0, 1.0, [100.0, 1000.0, 5000.0]),
            "eq": fingerprint(
                dsp.eq(x, SR, [{"type": "lowshelf", "f": 120, "gain_db": -3}, {"type": "highpass", "f": 30}])
            ),
            "gain_computer": dsp.gain_computer(np.array([-40.0, -26.0, -24.0, -20.0, -6.0]), -24.0, 4.0, 6.0),
            "compressor": fingerprint(y),
            "compressor_gr": fingerprint(gr),
            "compressor_rms": fingerprint(rms),
            "limiter": fingerprint(lim),
            "limiter_sample_peak": fingerprint(dsp.limiter(x * util.lin(6), SR, -1.0, true_peak=False)),
            "master_to": {"drive_db": drive, "integrated": L.integrated(mastered, SR), "out": fingerprint(mastered)},
            "clip": [fingerprint(dsp.clip(x * 4, -1.0, m)) for m in ("hard", "soft")],
            "quantize": [fingerprint(dsp.quantize(x, 8, d, s)) for d in ("none", "rpdf", "tpdf") for s in (False,)],
            "quantize_shaped": fingerprint(dsp.quantize(x[: SR // 4], 12, "tpdf", True)),
            "truncate": fingerprint(dsp.truncate(x, 10)),
            "gain": fingerprint(dsp.gain(x, -3.0)),
            "normalize_lufs": fingerprint(dsp.normalize_lufs(x, SR, -16.0)),
            "to_mono": fingerprint(dsp.to_mono(x)),
            "ms_width": fingerprint(dsp.ms_width(x, 3.0)),
            "excerpt": fingerprint(dsp.excerpt(x, SR, 1.0, 2.0)),
        },
    )


def test_compare(tmp_path) -> None:
    a = aio.from_array(mix(), SR, "a")
    b = aio.from_array(reference(-4.0) * util.lin(-5.0), SR, "b")
    matched, tgt = compare.match([a, b])
    on_section, tgt_section = compare.match([a, b], target=-20.0, section=(1.0, 3.0))
    kit = compare.abx_kit(a, b, str(tmp_path / "abx"), trials=6, start=1.0, dur=2.0, seed=7)
    with open(kit) as fh:
        key = json.load(fh)
    rows = {"mix": {"loudness.integrated": -12.5, "dynamics.crest_db": 9.1}}
    refs = {"r1": {"loudness.integrated": -8.0, "dynamics.crest_db": 7.0}, "r2": {"loudness.integrated": -9.5}}
    check(
        "compare",
        {
            "match_gains": [g for _, g in matched],
            "match_target": tgt,
            "match_out": [fingerprint(x) for x, _ in matched],
            "section_gains": [g for _, g in on_section],
            "section_target": tgt_section,
            "abx_key": {k: v for k, v in key.items() if k not in ("A", "B")},
            "abx_files": sorted(os.listdir(tmp_path / "abx")),
            "abx_score": compare.abx_score(str(tmp_path / "abx"), "".join(key["key"])),
            "abx_score_wrong": compare.abx_score(str(tmp_path / "abx"), "abab"),
            "binom": [compare.binom_p(k, 12) for k in (6, 9, 10, 12)],
        },
    )
    text("refs_table", compare.refs_table(rows["mix"], refs, ["loudness.integrated", "dynamics.crest_db", "missing"]))


def test_als(tmp_path) -> None:
    check(
        "als",
        {
            "live12": als.read(os.path.join(FIXTURES, "L12-automation.als")),
            "live10": als.read(os.path.join(FIXTURES, "example-140.als")),
        },
    )
    # every finding: a limiter on Main, a switched-off plugin, a deactivated track, hot faders
    with gzip.open(os.path.join(FIXTURES, "L12-automation.als")) as fh:
        raw = fh.read().decode()
    main_at = raw.index("<MainTrack")
    dev_at = raw.index("<Devices />", main_at)
    raw = (
        raw[:dev_at]
        + '<Devices><Limiter Id="900"><On><Manual Value="true" /></On><UserName Value="Lim" /></Limiter></Devices>'
        + raw[dev_at + len("<Devices />") :]
    )
    track_at = raw.index("<AudioTrack")
    dev_at = raw.index("<Devices />", track_at)
    raw = (
        raw[:dev_at]
        + '<Devices><PluginDevice Id="901"><On><Manual Value="false" /></On><UserName Value="" /><PluginDesc>'
        '<VstPluginInfo Id="0"><PlugName Value="Decapitator" /></VstPluginInfo></PluginDesc></PluginDevice></Devices>'
        + raw[dev_at + len("<Devices />") :]
    )
    speaker = raw.index("<Speaker>", track_at)
    raw = raw[:speaker] + raw[speaker:].replace('<Manual Value="true" />', '<Manual Value="false" />', 1)
    planted = tmp_path / "planted.als"
    with gzip.open(planted, "wb") as fh:
        fh.write(raw.encode())
    check("als_planted", als.read(str(planted)))


def test_io(tmp_path) -> None:
    x = mix()[: SR * 2]
    p24 = write(tmp_path / "x.wav", x, subtype="PCM_24")
    pf = write(tmp_path / "x.flac", x * 0.5, subtype="PCM_16")
    a24, af = aio.load(str(p24)), aio.load(str(pf))
    out = aio.save(str(tmp_path / "out" / "y.wav"), x[:, 0], SR)
    js = aio.dump_json(
        {"a": np.float64(1.5), "b": np.int64(3), "c": np.arange(3), "d": a24.meta()}, str(tmp_path / "j.json")
    )
    check(
        "io",
        {
            "wav": {**a24.meta(), "path": "x.wav", "n": a24.n, "ch": a24.ch, "x": fingerprint(a24.x)},
            "flac": {**af.meta(), "path": "x.flac", "x": fingerprint(af.x)},
            "saved": sf.info(out).subtype,
            "saved_shape": list(sf.read(out, always_2d=True)[0].shape),
            "array": {**aio.from_array(x[:, 0], SR).meta(), "ch": aio.from_array(x[:, 0], SR).ch},
            "json": json.loads(Path(js).read_text())["c"],
        },
    )


def test_util() -> None:
    x = mix()
    check(
        "util",
        {
            "db": [util.db(v) for v in (1.0, 0.5, 0.0, -0.25)],
            "pdb": [util.pdb(v) for v in (1.0, 0.5, 0.0)],
            "lin": util.lin([-6.0, 0.0, 6.0]),
            "rms": [util.rms(x), util.rms(np.zeros(0))],
            "r": [
                util.r(v) for v in (None, 1.23456, float("nan"), float("inf"), float("-inf"), "text", np.float64(2.555))
            ],
            "r3": util.r(1.23456, 3),
            "mono": fingerprint(util.mono(x)),
            "dc_offset": util.dc_offset_db(x + 0.001, SR),
            "dc_is_real": [util.dc_is_real(x + 0.001, SR), util.dc_is_real(x, SR), util.dc_is_real(x[:SR], SR)],
        },
    )


def test_review_feedback() -> None:
    x = mix()
    au = aio.from_array(x, SR, "mix")
    fl = measure.flat(measure.sheet(au))
    refs = {"r1": dict(fl, **{"loudness.plr": 3.0}), "r2": dict(fl, **{"loudness.plr": 4.0})}
    pm = premaster.run(au)
    peaks = review.peak_events(x, SR)
    check(
        "review_feedback",
        {"peaks": peaks, "feedback": review.feedback(pm, fl, peaks, refs), "short": review.peak_events(x[:SR], SR)},
    )


def test_hypothesis_ops() -> None:
    x = mix()[: SR * 4]
    ops = [
        {"op": "gain", "gain_db": -3},
        {"op": "eq", "bands": [{"type": "peak", "f": 350, "gain_db": 3, "q": 0.7}]},
        {"op": "compressor", "threshold": -20, "ratio": 3, "attack_ms": 5, "release_ms": 80},
        {"op": "limiter", "ceiling_db": -1.5},
        {"op": "master_to", "target_lufs": -12, "ceiling_db": -1.0},
        {"op": "clip", "ceiling_db": -3, "mode": "soft"},
        {"op": "quantize", "bits": 16, "dither": "rpdf"},
        {"op": "truncate", "bits": 12},
        {"op": "normalize_lufs", "target": -18},
        {"op": "mono"},
        {"op": "ms_width", "side_gain_db": -6},
        {"op": "excerpt", "start_s": 0.5, "dur_s": 1.0},
        {"op": "platform", "name": "youtube"},
        {"op": "platform", "name": "apple_music"},
    ]
    out = {f"{i}:{op['op']}": fingerprint(hypothesis.apply_op(x * util.lin(6), SR, op)) for i, op in enumerate(ops)}
    rows = {"a": {"m": 1.0, "n": None}, "b": {"m": 0.5}}
    preds = [
        {"metric": "m", "left": "a", "right": "b", "op": op, "value": v}
        for op, v in ((">", 0.4), ("<", 0.4), (">=", 0.5), ("abs<", 0.6), ("abs>", 0.6), ("<=", 0.49))
    ]
    preds += [
        {"metric": "m", "left": "a", "op": ">", "value": 0.99},
        {"metric": "n", "left": "a", "right": "b", "op": ">", "value": 0},
    ]
    check("hypothesis_ops", {"ops": out, "evaluate": [hypothesis.evaluate(p, rows) for p in preds]})


def test_siggen() -> None:
    check(
        "siggen",
        {
            "sine": fingerprint(siggen.sine(997.0, -6.0, 0.5, SR, ch=1, phase=0.3, fade_ms=5.0)),
            "pink_band": fingerprint(siggen.pink(1.0, SR, ch=1, seed=4, rms_dbfs=-18, band=(100, 4000))),
            "white": fingerprint(siggen.white(1.0, SR, seed=5)),
            "click": fingerprint(siggen.bandlimited_click(SR)),
            "comp_probe": fingerprint(siggen.comp_probe(8000)[0]),
            "comp_probe_layout": siggen.COMP_PROBE_LAYOUT,
            "eq_probe": fingerprint(siggen.eq_probe(8000, dur=2.0)),
            "kcal": {k: fingerprint(v) for k, v in siggen.kcal_files(8000, dur=1.0).items()},
            "kick_loop": fingerprint(siggen.kick_loop(SR, bars=1)),
        },
    )
