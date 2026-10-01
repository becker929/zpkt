"""`mlab refs --peaks` end to end on synthetic songs with known layouts."""
import json
import os
import sys

import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mlab import cli, siggen  # noqa: E402


def test_refs_peaks_cli(tmp_path, capsys):
    sr = 44100
    tgt, truth = siggen.song_sections(sr, 150.0)
    sf.write(tmp_path / "target.wav", tgt, sr)
    refdir = tmp_path / "refs"
    refdir.mkdir()
    for i, bpm in enumerate((145.0, 155.0)):
        x, _ = siggen.song_sections(sr, bpm, seed=i + 1)
        sf.write(refdir / f"ref{i}.wav", x, sr)
    out = tmp_path / "r.json"
    ex = tmp_path / "ex"
    cli.main(["refs", str(tmp_path / "target.wav"), str(refdir), "--peaks", "--json", str(out), "--excerpts", str(ex)])
    res = json.loads(out.read_text())
    s = res["structure"]["TARGET target"]
    assert s["main_break"] == truth["break"] and s["peak_bars"] == truth["peak"]
    assert len(res["third_octave_diff"]) > 20
    assert len(os.listdir(ex)) == 3
    assert "Structure" in capsys.readouterr().out
