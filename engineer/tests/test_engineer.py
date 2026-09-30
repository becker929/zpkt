"""engineer: the loop calls ears with a flag ears has; hypotheses run on ears' meters."""
from __future__ import annotations

import json
import os
import stat
import textwrap

import numpy as np
import soundfile as sf

from engineer import hypothesis
from engineer.loop import Loop
from taste.models import Verdict

SR = 44100


def _script(path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_loop_cycle_passes_ears_json_to_the_judge(tmp_path) -> None:
    calls = tmp_path / "calls.log"
    render = tmp_path / "render.wav"
    hands = _script(tmp_path / "hands", f'echo "hands $@" >> {calls}\n'
                    f'case "$1" in record) touch "$5";; esac\n')
    # A stand-in ears that only accepts the flag the real ears has.
    ears = _script(tmp_path / "ears", f'echo "ears $@" >> {calls}\n'
                   '[ "$3" = "--json" ] || { echo "unknown flag $3" >&2; exit 2; }\n'
                   'echo \'{"clip_id": "x", "audio_path": "r.wav"}\'\n')

    seen = {}

    class Judge:
        def judge(self, profile_json: str) -> Verdict:
            seen["profile"] = json.loads(profile_json)
            return Verdict(clip_id="x", score=3, rationale="stub")

    loop = Loop(hands_bin=hands, ears_bin=ears, store=object(), judge=Judge())
    verdict = loop.run_cycle(str(tmp_path / "config.json"), beats=8)

    assert verdict.score == 3
    assert seen["profile"]["clip_id"] == "x"
    log = calls.read_text()
    assert "hands execute" in log and "hands record" in log and "--json" in log


def test_hypothesis_runs_on_ears_meters(tmp_path, monkeypatch) -> None:
    t = np.arange(SR * 3) / SR
    tone = 0.25 * np.sin(2 * np.pi * 440 * t)
    sf.write(tmp_path / "tone.wav", np.stack([tone, tone], axis=1), SR, subtype="FLOAT")
    monkeypatch.setattr(hypothesis, "LAB", str(tmp_path))
    spec = tmp_path / "H900-gain.yaml"
    spec.write_text(textwrap.dedent("""\
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
        """))
    outdir, verdict = hypothesis.run(str(spec), outroot=str(tmp_path / "results"))
    result = json.loads(open(os.path.join(outdir, "result.json")).read())
    assert "SUPPORTED" in str(verdict).upper() or "PASS" in json.dumps(result)
