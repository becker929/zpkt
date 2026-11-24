"""`mlab target` and `mlab eqfit` end to end on synthetic files with known answers."""

import json
import os
import sys

import soundfile as sf
from scipy import signal as sps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import checks  # noqa: E402
from mlab import cli, dsp, siggen  # noqa: E402
from mlab import target as T  # noqa: E402

SR = 44100


def _refs_json(tmp_path, entries):
    path = tmp_path / "refs.json"
    path.write_text(json.dumps({"refs": entries}))
    return str(path)


def test_load_refs_paths_and_sets(tmp_path):
    p = _refs_json(
        tmp_path,
        [
            {"id": "a", "title": "A", "file": "a.flac", "drop": 24, "barSeconds": 1.5, "bpm": 160, "set": "hw002"},
            {"id": "b", "title": "B", "file": "sub/b.flac", "drop": 20, "barSeconds": 1.6, "bpm": 150, "set": "kk"},
        ],
    )
    refs = T.load_refs(p)
    assert [r["id"] for r in refs] == ["a", "b"]
    assert refs[1]["path"] == os.path.join(str(tmp_path), "sub/b.flac") and refs[1]["bar_s"] == 1.6
    assert [r["id"] for r in T.load_refs(p, "hw002")] == ["a"]
    assert T.load_refs(p, base_dir="/elsewhere")[0]["path"] == "/elsewhere/a.flac"


def test_target_cli(tmp_path, capsys):
    x = siggen.pink(16, SR, seed=41)
    sf.write(tmp_path / "mix.wav", x, SR, subtype="FLOAT")
    # references: the same noise through a +3 dB and a +6 dB high shelf; the second at 48 kHz
    shelf = [{"type": "highshelf", "f": 4000, "gain_db": 3, "q": 0.707}]
    sf.write(tmp_path / "r1.wav", dsp.eq(x, SR, shelf), SR, subtype="FLOAT")
    r2 = sps.resample_poly(dsp.eq(x, SR, [dict(shelf[0], gain_db=6)]), 160, 147, axis=0)
    sf.write(tmp_path / "r2.wav", r2, 48000, subtype="FLOAT")
    p = _refs_json(
        tmp_path,
        [
            {"id": "r1", "file": "r1.wav", "drop": 8, "barSeconds": 0.5, "set": "t"},
            {"id": "r2", "file": "r2.wav", "drop": 8, "barSeconds": 0.5, "set": "t"},
            {"id": "other", "file": "missing.wav", "drop": 8, "barSeconds": 0.5, "set": "u"},
        ],
    )
    out = tmp_path / "t.json"
    cli.main(
        [
            "target",
            str(tmp_path / "mix.wav"),
            "--refs",
            p,
            "--set",
            "t",
            "--drop",
            "8",
            "--bar",
            "0.5",
            "--json",
            str(out),
        ]
    )
    res = json.loads(out.read_text())
    assert set(res["gaps"]["windows"]) == {"build", "drop"}
    g = res["gaps"]["windows"]["drop"]
    assert g["n_refs"] == 2
    # the mix is darker than both references: air under their range, sub over it (rel LUFS)
    assert g["regions"]["air"]["outside"] < -1.0
    assert g["regions"]["sub"]["outside"] > 0.3
    assert abs(res["gaps"]["contrast_lu"]["diff"]) < 0.05
    printed = capsys.readouterr().out
    assert "== DROP" in printed and "Side minus mid" in printed and "1/3 octave" in printed


def test_eqfit_cli(tmp_path, capsys):
    st = checks.eqfit_stems(SR)
    for k, x in st.items():
        sf.write(tmp_path / f"{k}.wav", x, SR, subtype="FLOAT")
    ref = (
        dsp.eq(st["kick"], SR, [{"type": "peak", "f": 50, "gain_db": 6, "q": 1.0}])
        + st["stab"]
        + dsp.eq(st["hats"], SR, [{"type": "highshelf", "f": 8000, "gain_db": -6, "q": 0.707}])
    )
    sf.write(tmp_path / "ref.wav", ref, SR, subtype="FLOAT")
    p = _refs_json(tmp_path, [{"id": "ref", "file": "ref.wav", "drop": 8, "barSeconds": 0.5, "set": "t"}])
    moves = {
        "moves": {
            "k": [{"kind": "peak", "f": 50, "gain_db": [-12, 12], "q": 1.0}],
            "h": {"eq": [{"kind": "highshelf", "f": 8000, "gain_db": [-12, 12]}], "gain_db": [-3, 3]},
        },
        "weights": {"build": 0.0},
    }
    (tmp_path / "moves.json").write_text(json.dumps(moves))
    plan = tmp_path / "plan.json"
    cli.main(
        [
            "eqfit",
            "--stems",
            *(str(tmp_path / f"{k}.wav") for k in ("kick", "stab", "hats")),
            "--names",
            "k",
            "s",
            "h",
            "--moves",
            str(tmp_path / "moves.json"),
            "--refs",
            p,
            "--drop",
            "8",
            "--bar",
            "0.5",
            "--out",
            str(plan),
        ]
    )
    res = json.loads(plan.read_text())
    assert abs(res["plan"]["k"]["eq"][0]["gain_db"] - 6) < 0.5
    assert abs(res["plan"]["h"]["eq"][0]["gain_db"] + 6) < 0.5
    assert abs(res["plan"]["h"]["gain_db"]) < 0.25
    assert res["objective"]["weights"] == {"drop": 1.0}  # build weighted 0: left out
    assert res["model_check"]["drop"]["max_abs_err_db"] < 0.5
    assert "Model check" in capsys.readouterr().out
