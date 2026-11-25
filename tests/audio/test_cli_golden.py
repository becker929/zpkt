"""Every `mlab` command, run on synthetic files in a temporary lab: what it prints and what it writes, pinned.

Paths under the temporary folder print as <tmp>; anything that prints the clock is masked where it is read.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from golden_check import check, home_only, text
from signals import BEAT_S, SR, mix, reference, refs_json, write

from zpkt.audio.meters import cli, dsp, siggen
from zpkt.audio.meters.util import lin


def run(capsys: pytest.CaptureFixture[str], mask, *argv: str) -> str:
    cli.main(list(argv))
    return mask(capsys.readouterr().out)


def masked_json(path: Path, mask) -> object:
    return json.loads(mask(path.read_text()))


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    x = mix()
    out = {
        "mix": write(tmp_path / "mix.wav", x),
        "mix16": write(tmp_path / "mix16.wav", dsp.quantize(x * lin(-6), 16), subtype="PCM_16"),
        "bright": write(tmp_path / "bright.wav", reference(3.0)),
        "dark": write(tmp_path / "dark.wav", reference(-2.0) * lin(-5)),
    }
    refs = tmp_path / "refs"
    refs.mkdir()
    out["refs_dir"] = refs
    write(refs / "bright.wav", reference(3.0))
    write(refs / "dark.flac", reference(-2.0) * lin(-5), subtype="PCM_24")
    (refs / "notes.txt").write_text("not audio")
    return out


def test_measure(lab, files, capsys, masked) -> None:
    text("cli_measure", run(capsys, masked, "measure", str(files["mix"])))
    check("cli_measure_report", masked_json(lab / "reports" / "mix.json", masked))
    assert (lab / "reports" / "mix.md").read_text().startswith("# Measurement sheet — mix.wav")
    check("cli_measure_json", json.loads(run(capsys, masked, "measure", str(files["mix16"]), "--json")))


def test_premaster(lab, files, capsys, masked) -> None:
    text("cli_premaster", run(capsys, masked, "premaster", str(files["mix16"])))
    check("cli_premaster_json", json.loads(run(capsys, masked, "premaster", str(files["mix"]), "--json")))


def test_deliver(lab, files, capsys, masked) -> None:
    text("cli_deliver", run(capsys, masked, "deliver", str(files["mix"]), "--no-codecs"))
    check("cli_deliver_json", json.loads(run(capsys, masked, "deliver", str(files["bright"]), "--no-codecs", "--json")))


def test_bitdepth_and_spectrum(lab, files, capsys, masked) -> None:
    check("cli_bitdepth", json.loads(run(capsys, masked, "bitdepth", str(files["mix16"]))))
    out = run(capsys, masked, "spectrum", str(files["mix"]), "--ref", str(files["bright"]), "--phon", "60")
    check("cli_spectrum", json.loads(out))
    check("cli_spectrum_plain", json.loads(run(capsys, masked, "spectrum", str(files["dark"]))))


def test_eq_diff(lab, files, tmp_path, capsys, masked) -> None:
    x = mix()
    wet = dsp.eq(x, SR, [{"type": "peak", "f": 2000, "gain_db": -5, "q": 2.0}])
    wet_path = write(tmp_path / "wet.wav", np.vstack([np.zeros((128, 2)), wet]))
    check("cli_eq_diff", json.loads(run(capsys, masked, "eq-diff", str(files["mix"]), str(wet_path))))
    full = json.loads(run(capsys, masked, "eq-diff", str(files["mix"]), str(wet_path), "--json"))
    check("cli_eq_diff_full", full)


def test_comp_probe(lab, tmp_path, capsys, masked) -> None:
    sr = 16000
    probe, _ = siggen.comp_probe(sr)
    wet = dsp.compressor(probe, sr, -18, 4, 8, 150, 4, 0)
    dry_path = write(tmp_path / "probe.wav", probe, sr)
    wet_path = write(tmp_path / "wet.wav", np.vstack([np.zeros((200, 2)), wet]), sr)
    check("cli_comp_probe", json.loads(run(capsys, masked, "comp-probe", str(dry_path), str(wet_path))))


def test_probe_and_kcal(lab, capsys, masked) -> None:
    text("cli_probe", run(capsys, masked, "probe", "--sr", "8000"))
    probes = lab / "audio" / "renders" / "probes"
    assert sorted(os.listdir(probes)) == ["comp_probe.layout.json", "comp_probe.wav", "eq_probe_pink.wav"]
    check("cli_probe_layout", json.loads((probes / "comp_probe.layout.json").read_text()))
    text("cli_kcal", run(capsys, masked, "kcal", "--sr", "8000"))
    kdir = lab / "audio" / "renders" / "k-system"
    check("cli_kcal_files", sorted(os.listdir(kdir)))


def test_match_and_abx(lab, files, capsys, masked, monkeypatch) -> None:
    text("cli_match", run(capsys, masked, "match", str(files["mix"]), str(files["dark"])))
    text("cli_match_target", run(capsys, masked, "match", str(files["mix"]), str(files["bright"]), "--target", "-20"))
    check("cli_match_files", sorted(os.listdir(lab / "audio" / "renders" / "matched")))
    monkeypatch.setattr(os, "urandom", lambda n: b"\x00\x00\x00\x07"[:n])  # abx's key is random; fix its seed
    out = run(
        capsys, masked, "abx", str(files["mix"]), str(files["dark"]), "--trials", "4", "--start", "1", "--dur", "2"
    )
    text("cli_abx", out)
    kit = lab / "audio" / "renders" / "abx" / "mix_vs_dark"
    check("cli_abx_files", sorted(os.listdir(kit)))
    key = json.loads((kit / ".answer_key.json").read_text())
    check("cli_abx_key", {k: v for k, v in key.items() if k not in ("A", "B")})
    text("cli_abx_howto", (kit / "HOW_TO.md").read_text())
    check("cli_abx_score", json.loads(run(capsys, masked, "abx-score", str(kit), "".join(key["key"]))))


def test_als(lab, capsys, masked) -> None:
    fixtures = Path(__file__).resolve().parents[2] / "ears" / "mlab" / "calibration" / "fixtures"
    text("cli_als", run(capsys, masked, "als", str(fixtures / "L12-automation.als")))
    check("cli_als_json", json.loads(run(capsys, masked, "als", str(fixtures / "example-140.als"), "--json")))


def test_review(lab, files, tmp_path, capsys, masked, monkeypatch) -> None:
    out = run(capsys, masked, "review", str(files["mix"]), "--refs", str(files["refs_dir"]), "--no-codecs")
    text("cli_review", out)
    md = (lab / "reports" / "review-mix.md").read_text()
    text("cli_review_md", masked(md))
    check("cli_review_json", masked_json(lab / "reports" / "review-mix.json", masked))
    text(
        "cli_review_norefs",
        run(capsys, masked, "review", str(files["mix16"]), "--refs", str(tmp_path / "none"), "--no-codecs"),
    )


def test_refs(lab, files, capsys, masked) -> None:
    text("cli_refs", run(capsys, masked, "refs", str(files["mix"]), str(files["refs_dir"])))


def test_refs_peaks(lab, tmp_path, capsys, masked) -> None:
    sr = 44100  # the 2-16 kHz band that finds the peak needs a full-band rate
    tgt, _ = siggen.song_sections(sr, 150.0)
    write(tmp_path / "song.wav", tgt, sr)
    rdir = tmp_path / "songrefs"
    rdir.mkdir()
    for i, bpm in enumerate((145.0, 155.0)):
        write(rdir / f"ref{i}.wav", siggen.song_sections(sr, bpm, seed=i + 1)[0], sr)
    out_json, ex = tmp_path / "peaks.json", tmp_path / "ex"
    argv = ["refs", str(tmp_path / "song.wav"), str(rdir), "--peaks", "--json", str(out_json), "--excerpts", str(ex)]
    text("cli_refs_peaks", run(capsys, masked, *argv, "--target", "-16"))
    check("cli_refs_peaks_json", json.loads(out_json.read_text()))
    check("cli_refs_peaks_excerpts", sorted(os.listdir(ex)))


def test_target(lab, files, tmp_path, capsys, masked) -> None:
    r2 = write(tmp_path / "r2.wav", reference(-2.0), 48000)  # declared 48 kHz: the same samples, another rate
    p = refs_json(
        tmp_path,
        [
            {"id": "bright", "title": "Bright", "file": "bright.wav", "drop": 6, "barSeconds": BEAT_S, "set": "t"},
            {"id": "r2", "file": str(r2), "drop": 5.5, "barSeconds": BEAT_S, "set": "t"},
            {"id": "elsewhere", "file": "missing.wav", "drop": 6, "barSeconds": BEAT_S, "set": "u"},
        ],
    )
    out = tmp_path / "t.json"
    argv = ["target", str(files["mix"]), "--refs", str(p), "--set", "t", "--drop", "6", "--bar", str(BEAT_S)]
    text("cli_target", run(capsys, masked, *argv, "--json", str(out)))
    check("cli_target_json", masked_json(out, masked))
    with pytest.raises(SystemExit) as e:
        cli.main(["target", str(files["mix"]), "--refs", str(p), "--set", "none"])
    assert e.value.code == f"no references in {p} with set 'none'"


@home_only
def test_eqfit(lab, tmp_path, capsys, masked) -> None:
    import checks

    st = checks.eqfit_stems(SR)
    for k, x in st.items():
        write(tmp_path / f"{k}.wav", x)
    ref = (
        dsp.eq(st["kick"], SR, [{"type": "peak", "f": 55, "gain_db": 5, "q": 1.0}])
        + st["stab"] * lin(-1.0)
        + dsp.eq(st["hats"], SR, [{"type": "highshelf", "f": 7000, "gain_db": -4, "q": 0.707}])
    )
    write(tmp_path / "ref.wav", ref)
    p = refs_json(tmp_path, [{"id": "ref", "file": "ref.wav", "drop": 8, "barSeconds": 0.5, "set": "t"}])
    moves = {
        "kick": [{"kind": "peak", "f": [40, 80], "gain_db": [-9, 9], "q": 1.0}, {"gain_db": [-3, 3]}],
        "stab": {"eq": [{"kind": "lowshelf", "f": 250, "gain_db": [-6, 6]}], "gain_db": [-3, 3]},
        "hats": {
            "eq": [{"kind": "highshelf", "f": 7000, "gain_db": [-9, 9]}, {"kind": "highpass", "f": 200}],
            "gain_db": [-3, 3],
        },
    }
    (tmp_path / "moves.json").write_text(json.dumps({"moves": moves, "weights": {"build": 0.25}, "beta": 0.1}))
    plan = tmp_path / "plan.json"
    stems = [str(tmp_path / f"{k}.wav") for k in ("kick", "stab", "hats")]
    argv = ["eqfit", "--stems", *stems, "--moves", str(tmp_path / "moves.json"), "--refs", str(p), "--drop", "8"]
    text("cli_eqfit", run(capsys, masked, *argv, "--bar", "0.5", "--out", str(plan)))
    check("cli_eqfit_json", masked_json(plan, masked))
    with pytest.raises(SystemExit) as e:
        cli.main([*argv, "--names", "a", "a", "b"])
    assert e.value.code == "--names needs one unique name per stem"


def test_hyp_report(lab, tmp_path, capsys, masked, monkeypatch) -> None:
    from zpkt.audio.meters import hypothesis

    write(tmp_path / "tone.wav", siggen.sine(440, -12, 3.0, SR))
    monkeypatch.setattr(hypothesis, "LAB", str(tmp_path))
    monkeypatch.setattr(hypothesis, "ROOT", str(tmp_path))
    spec = tmp_path / "H901-mono.yaml"
    spec.write_text(
        "id: H901\ntitle: summing to mono\nchapter: '20-21'\nsource: test\nclaim: Mono keeps a dual-mono tone.\n"
        "inputs: {tone: tone.wav}\n"
        "variants:\n  - {name: as_is, from: tone}\n  - {name: mono, from: tone, chain: [{op: mono}, {op: gain, gain_db: -1}]}\n"
        "predictions:\n  - {metric: loudness.integrated, left: mono, right: as_is, op: 'abs<', value: 1.5, why: gain}\n"
        "  - {metric: loudness.true_peak, left: mono, op: '<', value: -12}\n"
        "listening: {abx: [as_is, mono], trials: 3}\n"
    )
    monkeypatch.setattr(os, "urandom", lambda n: b"\x00\x00\x00\x03"[:n])
    text("cli_hyp", run(capsys, masked, "hyp", "run", str(spec), "--no-codecs"))
    out = tmp_path / "hypotheses" / "results" / "H901-mono"
    report = re.sub(r"Run \d{4}-\d\d-\d\d \d\d:\d\d", "Run <time>", (out / "report.md").read_text())
    text("cli_hyp_report", masked(report))
    check("cli_hyp_result", json.loads((out / "result.json").read_text()))
    check("cli_hyp_files", sorted(os.listdir(out)) + sorted(os.listdir(out / "sheets")))


def test_calibrate_writes_the_report(lab, monkeypatch, capsys) -> None:
    import checks

    (lab / "calibration").mkdir()
    monkeypatch.setattr(checks, "ALL", [checks.check_kweighting])
    monkeypatch.setattr(checks, "LAB", str(lab))
    with pytest.raises(SystemExit) as e:
        cli.main(["calibrate", "--quick"])
    assert e.value.code == 0
    assert capsys.readouterr().out == "2/2 checks pass -> calibration/CALIBRATION.md\n"
    report = (lab / "calibration" / "CALIBRATION.md").read_text()
    assert "**2 / 2 checks pass.**" in report
    monkeypatch.setattr(checks, "ALL", [lambda: [checks.row("x", "planted failure", 1.0, 2.0, 0.1, "test")]])
    with pytest.raises(SystemExit) as e:
        cli.main(["calibrate", "--quick"])
    assert e.value.code == 1
    assert "FAIL x: planted failure: expected 1.0, got 2.0" in capsys.readouterr().out


def test_python_dash_m_and_usage(files) -> None:
    lab_root = Path(__file__).resolve().parents[2] / "ears" / "mlab"  # where people run `python3 -m mlab`
    res = subprocess.run(
        [sys.executable, "-m", "mlab", "bitdepth", str(files["mix16"])], capture_output=True, text=True, cwd=lab_root
    )
    assert res.returncode == 0 and json.loads(res.stdout)["effective_bits"] == 16
    res = subprocess.run([sys.executable, "-m", "mlab"], capture_output=True, text=True, cwd=lab_root)
    assert res.returncode == 2 and "usage: mlab" in res.stderr
    res = subprocess.run([sys.executable, "-m", "mlab", "--help"], capture_output=True, text=True, cwd=lab_root)
    commands = "measure premaster deliver bitdepth spectrum eq-diff comp-probe probe match abx abx-score kcal als"
    for name in [*commands.split(), "review", "refs", "target", "eqfit", "hyp", "calibrate"]:
        assert re.search(rf"\b{name}\b", res.stdout), name


def test_hypothesis_lab_dir_is_read_at_call_time(monkeypatch, tmp_path) -> None:
    from zpkt.audio.meters import hypothesis

    monkeypatch.setattr(hypothesis, "LAB", None)
    monkeypatch.setenv("MLAB_DATA", str(tmp_path))
    assert hypothesis.lab_dir() == str(tmp_path)
    assert hypothesis._p("x.wav") == str(tmp_path / "x.wav")
