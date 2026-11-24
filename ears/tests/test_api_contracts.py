"""The parts of mlab that other code calls, called the way that code calls them.

- hands (hands/src/hands/library/inventory.py, measure_mlab) runs a one-line program against mlab's Python API in
  a subprocess: io.load, then loudness.analyze, reading .integrated, .true_peak and .duration.
- The mix-climb spike (spikes/hw002_mixclimb/features.py), which hands/scripts/probe_pack/climb_live.py runs, calls
  loudness.integrated, spectrum.stereo_by_band, sections._rel_third_octave, dynamics.micro and transient_contrast.
- The mix desk (contrib/mixdesk/match.py) writes eqfit moves files and reads eqfit's plan back.
"""

from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
from mlab import dsp, eqfit, target
from mlab import dynamics as D
from mlab import io as aio
from mlab import loudness as L
from mlab import sections as SEC
from mlab import spectrum as S
from signals import SR, mix, write

# Copied from hands/src/hands/library/inventory.py (measure_mlab). If this has to change, hands has to change too.
HANDS_CODE = (
    "import json,sys;from mlab import io,loudness as L;a=io.load(sys.argv[1]);r=L.analyze(a.x,a.sr);"
    "print(json.dumps({'lufs':r.integrated,'true_peak':r.true_peak,'seconds':a.duration}))"
)


def test_hands_measure_program(tmp_path) -> None:
    path = write(tmp_path / "take.wav", mix(), subtype="PCM_24")
    out = subprocess.run([sys.executable, "-c", HANDS_CODE, str(path)], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    au = aio.load(str(path))
    res = L.analyze(au.x, au.sr)
    assert got == {"lufs": res.integrated, "true_peak": res.true_peak, "seconds": 12.0}


def test_spike_calls() -> None:
    x = mix()[: SR * 4]
    assert np.isfinite(L.integrated(x, SR))
    st = S.stereo_by_band(x, SR)
    assert [row["band_hz"] for row in st] == [[20, 120], [120, 500], [500, 2000], [2000, 8000], [8000, 20000]]
    assert {"correlation", "side_minus_mid_db"} <= set(st[0])
    rel = SEC._rel_third_octave(x, SR)
    assert len(rel) == 29 and all(len(pair) == 2 for pair in rel)
    assert "block_crest_median_db" in D.micro(x, SR)
    assert "transient_contrast_median_db" in D.transient_contrast(x, SR)


def test_mixdesk_moves_and_plan() -> None:
    """match.py eqfit_moves writes {stem: {"eq": [{kind, f, gain_db, q}], "gain_db"}}; plan_from_fit reads
    plan[stem]["eq"][i]["f" | "gain_db" | "q"] (bands in the order given) and plan[stem]["gain_db"]."""
    sr = SR
    rng = np.random.default_rng(5)
    stems = {name: rng.standard_normal((sr * 8, 2)) * 0.05 for name in ("Kick", "Bass")}
    wins = target.windows(4.0, 0.5)
    ref = dsp.eq(stems["Kick"], sr, [{"type": "peak", "f": 60, "gain_db": 3, "q": 1.0}]) + stems["Bass"]
    stats = target.ref_stats({"ref": target.profile(ref, sr, wins, 0.5)})
    moves = {
        "Kick": {"eq": [{"kind": "peak", "f": 60, "gain_db": [-6, 6], "q": 1.0}], "gain_db": 0.0},
        "Bass": {"eq": [{"kind": "lowshelf", "f": 100, "gain_db": 0.0, "q": 0.7}], "gain_db": [-2, 2]},
    }
    res = eqfit.fit(stems, sr, wins, stats, moves, bar_s=0.5, n_starts=2, measure=False)
    plan = res["plan"]
    assert list(plan) == ["Kick", "Bass"]
    for stem in plan:
        assert set(plan[stem]) == {"gain_db", "eq"}
        assert all(set(b) == {"kind", "f", "gain_db", "q"} for b in plan[stem]["eq"])
    assert plan["Kick"]["eq"][0]["f"] == 60.0 and plan["Bass"]["eq"][0]["q"] == 0.7
