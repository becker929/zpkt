"""`mlab hyp run` end to end on a tone with a known answer: +6 dB of gain is 6 LU louder."""
import json
import textwrap

import numpy as np
import soundfile as sf

from mlab import cli, hypothesis

SR = 44100
SPEC = textwrap.dedent("""\
    id: H900
    title: +6 dB of gain raises integrated loudness by 6 LU
    chapter: "17-19"
    source: test
    claim: Gain is gain.
    inputs: {tone: tone.wav}
    variants:
      - {name: as_is, from: tone}
      - {name: louder, from: tone, chain: [{op: gain, gain_db: 6}]}
    metrics: [loudness.integrated]
    predictions:
      - {metric: loudness.integrated, left: louder, right: as_is, op: ">", value: 5.9}
    codecs: false
    """)


def _lab(tmp_path, monkeypatch, spec=SPEC):
    """A lab in tmp_path: inputs and results both resolve there."""
    t = np.arange(SR * 3) / SR
    tone = 0.25 * np.sin(2 * np.pi * 440 * t)
    sf.write(tmp_path / "tone.wav", np.stack([tone, tone], axis=1), SR, subtype="FLOAT")
    monkeypatch.setattr(hypothesis, "LAB", str(tmp_path))
    monkeypatch.setattr(hypothesis, "ROOT", str(tmp_path))
    path = tmp_path / "H900-gain.yaml"
    path.write_text(spec)
    return path


def test_hypothesis_runs_on_the_meters(tmp_path, monkeypatch):
    spec = _lab(tmp_path, monkeypatch)
    outdir, verdict = hypothesis.run(str(spec), outroot=str(tmp_path / "out"))
    result = json.loads((tmp_path / "out" / "H900-gain" / "result.json").read_text())
    assert verdict == result["verdict"] == "SUPPORTED"
    assert result["predictions"][0]["status"] == "PASS"


def test_hyp_run_cli(tmp_path, monkeypatch, capsys):
    # --no-codecs overrides the YAML's codecs: true, so no codec round trip runs
    spec = _lab(tmp_path, monkeypatch, SPEC.replace("codecs: false", "codecs: true"))
    cli.main(["hyp", "run", str(spec), "--no-codecs"])
    out = tmp_path / "hypotheses" / "results" / "H900-gain"
    assert capsys.readouterr().out.strip() == f"SUPPORTED  →  {out}"
    assert (out / "report.md").read_text().startswith("# H900")
    assert "codec_roundtrip" not in json.loads((out / "sheets" / "louder.json").read_text())["delivery"]
