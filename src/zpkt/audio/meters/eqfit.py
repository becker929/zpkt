"""EQ moves on stems whose sum matches a target.

Inputs: solo renders of the mix's buses ("stems": same rate and length,
time-aligned, so their sum is close to the mix), the windows of
target.windows, the references' statistics per window (target.ref_stats:
mean, min and max per 1/3-octave band) and a moves spec saying which EQ
bands and faders may move, and how far.

Moves spec, per stem: {"eq": [bands], "gain_db": fader}, or a list of bands
that may include one {"gain_db": fader} entry. A band is
{"kind": peak|lowshelf|highshelf|highpass|lowpass, "f", "gain_db", "q"}.
A number is fixed; a [lo, hi] pair is free within those bounds. Defaults:
gain_db 0, q 0.707. Filters are the RBJ biquads of dsp.biquad (shelf q is
the cookbook Q). The fader is a stem's gain_db, fixed 0 unless given.
Example: {"kick": [{"kind": "peak", "f": [40, 70], "gain_db": [-6, 6], "q": 1}],
          "hats": {"eq": [{"kind": "highshelf", "f": 8000, "gain_db": [-9, 3]}], "gain_db": [-3, 3]}}

Model. Per stem and window, the PSD of target.profile (target.psd: 0.75 s
Hann segments, even time weight, channel-averaged), integrated into fine sub-bands: 1/48 octave,
split at every band and region edge. The predicted mix power in a sub-band is
    sum over stems of g^2 * |H(f)|^2 * P_stem
Powers add: correlation between stems is ignored. That is exact for
uncorrelated stems; the model check below says how far off it is for real
ones. Band and region levels are sums of sub-bands. Loudness is the
K-weighted power (loudness.k_weighting evaluated on the grid) plus an
offset per window, set so the unmodified prediction equals
loudness.integrated() of the actual stem sum (gating folds into that offset).
Bands are then dB rel predicted LUFS, exactly comparable with target.profile.

Objective (minimised):
    J = sum_w weight_w * sum_b [outside_b^2 + alpha * diff_b^2]
        + beta * sum_g (g / 6)^2
over windows w (default weights: drop 1.0, build 0.5, any other 1.0) and
1/3-octave bands b from 31.5 Hz to 16 kHz. diff = predicted - refs' mean;
outside = how far the band sits outside the refs' [min, max] (0 inside).
The last term charges every free gain g in dB (EQ band gains and faders).
alpha defaults to 0: a band inside the references' range costs nothing, so
the move cost keeps every gain that buys nothing at 0 dB. (At alpha 0.25 the
pull to the refs' mean was ~180x the move cost: in-range bands got walked to
the mean, and one outlier reference dragged it; LEARNINGS L-024.)
diff is still reported. Highpass and lowpass bands have no gain and no move cost.

Unreachable bands are left out of J: a band whose no-move prediction sits more
than UNREACHABLE_DB under the refs' min has no content there, and EQ cannot
supply it. One such band (50-90 dB outside) would outweigh every other band
and push unrelated levers. They are listed in the output per window.

When every stem has a free fader, a common gain on all of them changes no
dB rel LUFS value. The fit removes that common mode after the optimiser: the
free faders shift by their median (within bounds), so one fader that must move
is not spread over all of them.

Optimiser: scipy L-BFGS-B within the bounds, from several deterministic
starts (a neutral one, then seeded uniform draws); the lowest J wins.
Frequencies and Qs move in log space. Each start reports whether it converged.

Measured check (`measured` in the output, when stems are given): the plan is
applied to the stems with dsp.eq and the EQ'd sum measured with target.profile.
The prediction holds each window's LUFS offset fixed at its no-move value, but
gated loudness is not linear in a stem's level (a riser over a quiet bed moves
which blocks pass the gate). Windows whose measured and predicted LUFS change
differ by more than LUFS_FLAG_LU are flagged.

Model check: predicted (no moves) vs measured band levels of the actual
stem sum, max abs error in dB over 31.5 Hz-16 kHz.

Known answers: calibration/checks.py (check_eqfit).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import optimize

from . import bands as B
from . import dsp
from . import loudness as L
from . import target as T
from . import windows as W
from .arrays import ComplexArray, FloatArray, Json
from .util import pdb

KINDS = ("peak", "lowshelf", "highshelf", "highpass", "lowpass")
GAINED = ("peak", "lowshelf", "highshelf")
WEIGHTS = {"drop": 1.0, "build": 0.5}
ALPHA, BETA = 0.0, 0.05
UNREACHABLE_DB = 20.0  # no-move band this far under the refs' min: left out of J
LUFS_FLAG_LU = 0.5  # measured vs predicted LUFS change beyond this: flagged
STEM_KEYS = {"eq", "bands", "gain_db"}
BAND_KEYS = {"kind", "type", "f", "gain_db", "q"}
Q_DEFAULT = 0.707
SUB_PER_OCT = 48
F_LOW = 5.0  # sub-bands are log-spaced from here; [0, F_LOW) is one sub-band


# ------------------------------------------------------------------ responses
def _h2(kind: str, f0: float, sr: int, gain_db: float, q: float, z1: ComplexArray) -> FloatArray:
    """|H|^2 of one RBJ biquad at z1 = exp(-j w)."""
    b, a = dsp.biquad(kind, f0, sr, gain_db, q)
    z2 = z1 * z1
    return np.abs(b[0] + b[1] * z1 + b[2] * z2) ** 2 / np.abs(a[0] + a[1] * z1 + a[2] * z2) ** 2


def _is_band(d: Any) -> bool:
    return isinstance(d, dict) and ("kind" in d or "type" in d)


def _stem_plan(sp: Any) -> Json:
    """One stem's plan as {"gain_db", "eq"}: from that dict, a single band dict, or a list of bands
    that may hold one {"gain_db": ...} fader entry (as parse_moves accepts)."""
    if not sp:
        return {"gain_db": 0.0, "eq": []}
    if _is_band(sp):
        return {"gain_db": 0.0, "eq": [sp]}
    if isinstance(sp, list):
        faders = [b for b in sp if not _is_band(b)]
        return {
            "gain_db": float(sum(b.get("gain_db", 0.0) or 0.0 for b in faders)),
            "eq": [b for b in sp if _is_band(b)],
        }
    return {"gain_db": float(sp.get("gain_db", 0.0) or 0.0), "eq": sp.get("eq", sp.get("bands", []))}


def _power_gain(sp: Any, sr: int, z1: ComplexArray) -> FloatArray:
    sp = _stem_plan(sp)
    h = np.full(z1.shape, 10 ** (sp["gain_db"] / 10))
    for bd in sp["eq"]:
        kind = bd.get("kind", bd.get("type"))
        h = h * _h2(kind, bd["f"], sr, bd.get("gain_db", 0.0) if kind in GAINED else 0.0, bd.get("q", Q_DEFAULT), z1)
    return h


def response_db(plan: Any, freqs: npt.ArrayLike, sr: int) -> Any:
    """dB response of a plan at freqs (fader + every band). `plan` is one band, a list of bands
    (with at most one {"gain_db"} fader entry), one stem's {"gain_db", "eq"}, or a whole plan
    {stem: ...} (returns {stem: curve})."""
    if isinstance(plan, dict) and not _is_band(plan) and not (STEM_KEYS & set(plan)):
        return {k: response_db(v, freqs, sr) for k, v in plan.items()}
    z1 = np.exp(-2j * np.pi * np.asarray(freqs, dtype=float) / sr)
    return 10 * np.log10(np.maximum(_power_gain(plan, sr, z1), 1e-30))


# ------------------------------------------------------------------ model
def subband_edges(sr: int) -> FloatArray:
    """0, F_LOW, then 1/48-octave steps to Nyquist, plus every 1/3-octave band and region edge."""
    top = sr / 2
    k = np.arange(int(np.floor(np.log2(top / F_LOW) * SUB_PER_OCT)) + 1)
    _, blo, bhi = B.third_octave_grid(sr)
    rlo, rhi = B.region_edges(sr)
    e = np.unique(np.concatenate([[0.0, top], F_LOW * 2 ** (k / SUB_PER_OCT), blo, bhi, rlo, rhi]))
    e = e[e <= top]
    return e[np.concatenate([[True], np.diff(e) > 1e-6])]


def _ix(e: FloatArray, v: float) -> int:
    return int(np.argmin(np.abs(e - v)))


class Model:
    """Sub-band powers of each stem per window, and the measured stem sum for the model check."""

    def __init__(
        self, stems: Mapping[str, Any], sr: int, wins: Mapping[str, W.Span], bar_s: float | None = None
    ) -> None:
        self.names = list(stems)
        xs = [T._stereo(stems[k]) for k in self.names]
        n = min(len(x) for x in xs)
        xs = [x[:n] for x in xs]
        self.sr = sr
        self.trimmed_s = (max(len(np.asarray(v)) for v in stems.values()) - n) / sr  # cut to the shortest stem
        e = subband_edges(sr)
        lo, hi = e[:-1], e[1:]
        self.fc = np.where(lo > 0, np.sqrt(lo * np.maximum(hi, lo)), hi / 2)
        self.z1 = np.exp(-2j * np.pi * self.fc / sr)
        self.kw2 = np.ones_like(self.fc)
        for num, den in L.k_weighting(sr):
            z2 = self.z1 * self.z1
            self.kw2 *= (
                np.abs(num[0] + num[1] * self.z1 + num[2] * z2) ** 2
                / np.abs(den[0] + den[1] * self.z1 + den[2] * z2) ** 2
            )
        c, blo, bhi = B.third_octave_grid(sr)
        self.band_hz = [T._hz(v) for v in c]
        self.band_ix = np.array([(_ix(e, a), _ix(e, b)) for a, b in zip(blo, bhi, strict=True)])
        self.region_ix = {k: (_ix(e, a), _ix(e, b)) for k, a, b in zip(B.REGION_KEYS, *B.region_edges(sr), strict=True)}
        keep, self.skipped = W.segments(sum(xs), sr, wins, bar_s)
        self.windows: dict[str, Json] = {}
        for w, ((a, b), seg) in keep.items():
            lufs = L.integrated(seg, sr)
            if not np.isfinite(lufs):
                self.skipped[w] = "silent (below the -70 LUFS gate)"
                continue
            i0, i1 = round(a * sr), round(b * sr)
            P = np.array([T.band_power(*T.psd(x[i0:i1], sr), lo, hi) for x in xs])  # stems x sub-bands
            bands, regions = T.spectral(seg, sr, lufs)
            self.windows[w] = {
                "span_s": [a, b],
                "P": P,
                "lufs": float(lufs),
                "offset": float(lufs - pdb(np.sum(self.kw2 * P.sum(axis=0)))),
                "measured_bands": bands,
                "measured_regions": regions,
            }

    def gains(self, plan: Mapping[str, Any]) -> FloatArray:
        """stems x sub-bands power gains of a plan {stem: list of bands or {"gain_db", "eq"}}."""
        return np.array([_power_gain(plan.get(k), self.sr, self.z1) for k in self.names])

    def levels(self, G: FloatArray, w: str) -> tuple[float, FloatArray]:
        win = self.windows[w]
        pred = np.sum(G * win["P"], axis=0)
        lufs = win["offset"] + pdb(np.sum(self.kw2 * pred))
        cs = np.concatenate([[0.0], np.cumsum(pred)])
        return lufs, cs

    def predict(self, plan: Mapping[str, Any]) -> dict[str, Json]:
        """{window: {"lufs", "bands": [[hz, dB rel LUFS]], "regions": {key: dB rel LUFS}}}."""
        G, out = self.gains(plan), {}
        for w in self.windows:
            lufs, cs = self.levels(G, w)
            bv = pdb(cs[self.band_ix[:, 1]] - cs[self.band_ix[:, 0]]) - lufs
            out[w] = {
                "lufs": float(lufs),
                "bands": [[hz, float(v)] for hz, v in zip(self.band_hz, bv, strict=True)],
                "regions": {k: float(pdb(cs[j] - cs[i]) - lufs) for k, (i, j) in self.region_ix.items()},
            }
        return out

    def check(self) -> dict[str, Json]:
        """Model check: predicted (no moves) minus measured bands of the stem sum, per window."""
        out: dict[str, Json] = {}
        for w, p in self.predict({}).items():
            meas = {T._hz(c): v for c, v in self.windows[w]["measured_bands"]}
            err = [(hz, v - meas[hz]) for hz, v in p["bands"] if B.in_score(hz) and hz in meas]
            if not err:
                continue
            hz, e = max(err, key=lambda t: abs(t[1]))
            out[w] = {
                "max_abs_err_db": float(abs(e)),
                "at_hz": hz,
                "rms_err_db": float(np.sqrt(np.mean([v * v for _, v in err]))),
                "bands": [[h, float(v)] for h, v in err],
            }
        return out


# ------------------------------------------------------------------ moves
def parse_moves(moves: Mapping[str, Any], names: Sequence[str], sr: int) -> tuple[dict[str, Json], list[Json]]:
    """-> (spec, params). spec {stem: {"gain_db": slot, "eq": [{"kind", "f": slot, "gain_db": slot, "q": slot}]}},
    where a slot is ("fixed", value) or ("free", index into params)."""
    spec: dict[str, Json] = {}
    params: list[Json] = []

    def slot(stem: str, where: str, key: str, kind: str, v: Any, log: bool) -> tuple[str, Any]:
        if isinstance(v, (list, tuple)):
            lo, hi = float(v[0]), float(v[1])
            if lo > hi:
                raise ValueError(f"{stem} {where}: bounds {v} are reversed")
            if key == "f":
                lo, hi = max(lo, 1.0), min(hi, 0.49 * sr)
            if log and lo <= 0:
                raise ValueError(f"{stem} {where}: {key} must be > 0")
            if hi - lo > 1e-12:
                params.append({"stem": stem, "param": where, "kind": kind, "lo": lo, "hi": hi, "log": log})
                return ("free", len(params) - 1)
            v = lo
        v = float(v)
        if key == "f" and not 0 < v < sr / 2:
            raise ValueError(f"{stem} {where}: f = {v} Hz is outside 0..{sr / 2:g} Hz")
        if key == "q" and v <= 0:
            raise ValueError(f"{stem} {where}: q must be > 0")
        return ("fixed", v)

    for stem, m in moves.items():
        if stem not in names:
            raise ValueError(f"moves name {stem!r} is not one of the stems {names}")
        if isinstance(m, dict) and set(m) - STEM_KEYS:
            raise ValueError(
                f"{stem}: keys {sorted(set(m) - STEM_KEYS)} are not stem keys {sorted(STEM_KEYS)};"
                ' write one EQ band as a list: [{"kind": ...}]'
            )
        if isinstance(m, list):  # bands, plus at most one {"gain_db": ...} fader entry
            faders = [b for b in m if not _is_band(b)]
            for b in faders:
                if set(b) - {"gain_db"}:
                    raise ValueError(
                        f'{stem}: entry {b} has no kind, so it must be a fader {{"gain_db": ...}}'
                        f" (unknown keys {sorted(set(b) - {'gain_db'})})"
                    )
            if len(faders) > 1:
                raise ValueError(f"{stem}: more than one fader entry")
            m = {
                "eq": [b for b in m if "kind" in b or "type" in b],
                "gain_db": faders[0].get("gain_db", 0.0) if faders else 0.0,
            }
        s: Json = {"gain_db": slot(stem, "gain_db", "gain_db", "fader", m.get("gain_db", 0.0), False), "eq": []}
        for i, bd in enumerate(m.get("eq", m.get("bands", []))):
            kind = bd.get("kind", bd.get("type"))
            if set(bd) - BAND_KEYS:
                raise ValueError(f"{stem} eq[{i}]: unknown keys {sorted(set(bd) - BAND_KEYS)}")
            if kind not in KINDS:
                raise ValueError(f"{stem} eq[{i}]: kind {kind!r} is not one of {KINDS}")
            if "f" not in bd:
                raise ValueError(f"{stem} eq[{i}]: f is required")
            if kind not in GAINED and isinstance(bd.get("gain_db"), (list, tuple)):
                raise ValueError(f"{stem} eq[{i}]: a {kind} has no gain to move")
            s["eq"].append(
                {
                    "kind": kind,
                    "f": slot(stem, f"eq[{i}].f", "f", kind, bd["f"], True),
                    "gain_db": slot(
                        stem,
                        f"eq[{i}].gain_db",
                        "gain_db",
                        kind,
                        bd.get("gain_db", 0.0) if kind in GAINED else 0.0,
                        False,
                    ),
                    "q": slot(stem, f"eq[{i}].q", "q", kind, bd.get("q", Q_DEFAULT), True),
                }
            )
        spec[stem] = s
    return spec, params


def _value(sl: tuple[str, Any], vals: Sequence[float]) -> float:
    return sl[1] if sl[0] == "fixed" else float(vals[sl[1]])


def realize(spec: Mapping[str, Json], vals: Sequence[float]) -> dict[str, Json]:
    """Concrete plan {stem: {"gain_db", "eq": [{"kind", "f", "gain_db", "q"}]}} for parameter values."""
    return {
        stem: {
            "gain_db": _value(s["gain_db"], vals),
            "eq": [
                {
                    "kind": b["kind"],
                    "f": _value(b["f"], vals),
                    "gain_db": _value(b["gain_db"], vals),
                    "q": _value(b["q"], vals),
                }
                for b in s["eq"]
            ],
        }
        for stem, s in spec.items()
    }


def _x_bounds(params: Sequence[Json]) -> tuple[FloatArray, FloatArray]:
    lo = np.array([np.log(p["lo"]) if p["log"] else p["lo"] for p in params])
    hi = np.array([np.log(p["hi"]) if p["log"] else p["hi"] for p in params])
    return lo, hi


def _to_vals(params: Sequence[Json], x: Sequence[float] | FloatArray) -> list[float]:
    return [float(np.exp(v)) if p["log"] else float(v) for p, v in zip(params, x, strict=True)]


def starts(params: Sequence[Json], n: int) -> list[FloatArray]:
    """Neutral start (gains 0 dB or the bound nearest it, f and q mid-range in log), then seeded
    uniform draws: the same starts on every run."""
    lo, hi = _x_bounds(params)
    x0 = np.where([p["log"] for p in params], (lo + hi) / 2, np.clip(0.0, lo, hi))
    rng = np.random.default_rng(20261122)
    return [x0] + [lo + rng.random(len(lo)) * (hi - lo) for _ in range(max(0, n - 1))]


# ------------------------------------------------------------------ fit
def _compare(pred: Json, tw: Json) -> Json:
    """Predicted window levels against the refs' statistics (target.gap per band and region)."""
    tb = {b["hz"]: b for b in tw["bands"]}
    bands = [{"hz": hz, **g} for hz, v in pred["bands"] if (g := T.gap(v, tb.get(hz)))]
    for b in bands:
        b.pop("values", None)
    regions = {}
    for k in B.REGION_KEYS:
        g = T.gap(pred["regions"][k], tw["regions"].get(k))
        if g:
            g.pop("values", None)
        regions[k] = g
    return {"bands": bands, "regions": regions, "score": T.score(bands)}


def apply_plan(stems: Mapping[str, Any], sr: int, plan: Mapping[str, Any]) -> dict[str, FloatArray]:
    """The stems with a plan applied (dsp.eq in series, then the fader)."""
    out: dict[str, FloatArray] = {}
    for k, x in stems.items():
        sp = _stem_plan(plan.get(k))
        y = dsp.eq(
            np.asarray(x, dtype=float),
            sr,
            [
                {
                    "type": b.get("kind", b.get("type")),
                    "f": b["f"],
                    "gain_db": b.get("gain_db", 0.0) if b.get("kind", b.get("type")) in GAINED else 0.0,
                    "q": b.get("q", Q_DEFAULT),
                }
                for b in sp["eq"]
            ],
        )
        out[k] = y * 10 ** (sp["gain_db"] / 20)
    return out


def measured_check(
    model: Model,
    stems: Mapping[str, Any],
    plan: Mapping[str, Any],
    wins: Mapping[str, W.Span],
    bar_s: float | None = None,
) -> dict[str, Json]:
    """Apply the plan to the stems, measure the EQ'd sum with target.profile and compare with the
    prediction, per window: LUFS change (measured vs predicted) and the worst band error (dB rel LUFS)
    over 31.5 Hz-16 kHz. `flag` is set where the LUFS changes differ by more than LUFS_FLAG_LU."""
    xs = apply_plan({k: T._stereo(stems[k]) for k in model.names}, model.sr, plan)
    n = min(len(x) for x in xs.values())
    prof = T.profile(sum(x[:n] for x in xs.values()), model.sr, wins, bar_s)
    pred = model.predict(plan)
    out: dict[str, Json] = {}
    for w, pw in pred.items():
        mw = prof["windows"].get(w)
        if not mw:
            continue
        meas = {T._hz(c): v for c, v in mw["bands"]}
        err = [(hz, v - meas[hz]) for hz, v in pw["bands"] if B.in_score(hz) and hz in meas]
        hz, e = max(err, key=lambda t: abs(t[1])) if err else (None, float("nan"))
        d_meas = mw["lufs"] - model.windows[w]["lufs"]
        d_pred = pw["lufs"] - model.windows[w]["lufs"]
        out[w] = {
            "lufs_change_measured_lu": float(d_meas),
            "lufs_change_predicted_lu": float(d_pred),
            "lufs_error_lu": float(d_pred - d_meas),
            "max_abs_band_err_db": float(abs(e)),
            "at_hz": hz,
            "flag": bool(abs(d_pred - d_meas) > LUFS_FLAG_LU),
        }
    return out


def _decommon(params: Sequence[Json], vals: list[float], names: Sequence[str]) -> list[float]:
    """When every stem has a free fader, shift those faders by their median (clipped so all stay in
    bounds). Every dB rel LUFS value is unchanged; one fader move stays one move."""
    fad = {p["stem"]: i for i, p in enumerate(params) if p["param"] == "gain_db"}
    if not names or set(fad) != set(names):
        return vals
    ix = list(fad.values())
    v = np.array([vals[i] for i in ix])
    lo = max(params[i]["lo"] - vals[i] for i in ix)
    hi = min(params[i]["hi"] - vals[i] for i in ix)
    shift = float(np.clip(-np.median(v), lo, hi)) if lo <= hi else 0.0
    vals = list(vals)
    for i in ix:
        vals[i] += shift
    return vals


def fit(
    stems: Mapping[str, Any],
    sr: int,
    wins: Mapping[str, W.Span],
    targets: Json,
    moves: Mapping[str, Any],
    bar_s: float | None = None,
    weights: Mapping[str, float] | None = None,
    alpha: float = ALPHA,
    beta: float = BETA,
    n_starts: int = 6,
    model: Model | None = None,
    maxiter: int = 500,
    measure: bool = True,
) -> Json:
    """Fit the free parameters of `moves` so the predicted stem sum matches `targets`
    (target.ref_stats of the references). Returns values, plan, before/after gaps, model check,
    and (measure=True) the measured check of the plan on the actual stems."""
    model = model or Model(stems, sr, wins, bar_s)
    spec, params = parse_moves(moves, model.names, sr)
    ws = dict(WEIGHTS, **(weights or {}))
    before = model.predict({})
    terms: list[tuple[Any, ...]] = []
    unreachable: dict[str, list[Json]] = {}
    for w in model.windows:
        tw = targets.get("windows", {}).get(w)
        if not tw or ws.get(w, 1.0) <= 0:
            continue
        tb = {b["hz"]: b for b in tw["bands"]}
        b0 = dict((hz, v) for hz, v in before[w]["bands"])
        sel: list[int] = []
        dead: list[int] = []
        for k, hz in enumerate(model.band_hz):
            if not (B.in_score(hz) and hz in tb):
                continue
            (dead if b0[hz] < tb[hz]["min"] - UNREACHABLE_DB else sel).append(k)
        unreachable[w] = [
            {"hz": model.band_hz[k], "mix": float(b0[model.band_hz[k]]), "ref_min": tb[model.band_hz[k]]["min"]}
            for k in dead
        ]
        if sel:
            st = [tb[model.band_hz[k]] for k in sel]
            terms.append(
                (
                    w,
                    ws.get(w, 1.0),
                    model.band_ix[sel, 0],
                    model.band_ix[sel, 1],
                    np.array([s["mean"] for s in st]),
                    np.array([s["min"] for s in st]),
                    np.array([s["max"] for s in st]),
                )
            )
    if not terms:
        raise ValueError(
            f"no window has both stems and reachable targets (stems: {list(model.windows)}, "
            f"targets: {list(targets.get('windows', {}))})"
        )
    free_stems = {p["stem"] for p in params}
    G_fixed = model.gains({k: v for k, v in realize(spec, [0.0] * len(params)).items() if k not in free_stems})
    rows = {k: i for i, k in enumerate(model.names)}
    gain_ix = np.array([i for i, p in enumerate(params) if p["param"].endswith("gain_db")], dtype=int)

    def data_term(G: FloatArray) -> float:
        tot = 0.0
        for w, wt, first, last, mean, lo, hi in terms:
            lufs, cs = model.levels(G, w)
            v = pdb(cs[last] - cs[first]) - lufs
            d = v - mean
            o = np.where(v > hi, v - hi, np.where(v < lo, v - lo, 0.0))
            tot += wt * float(o @ o + alpha * (d @ d))
        return tot

    def obj_vals(vals: Sequence[float]) -> float:
        plan = realize(spec, vals)
        G = G_fixed.copy()
        for k in free_stems:
            G[rows[k]] = _power_gain(plan[k], sr, model.z1)
        g = np.asarray(vals)[gain_ix] if gain_ix.size else np.zeros(0)
        return data_term(G) + beta * float(np.sum((g / 6.0) ** 2))

    def objective(x: FloatArray) -> float:
        return obj_vals(_to_vals(params, x))

    lo, hi = _x_bounds(params)
    runs: list[Json] = []
    if params:
        maxfun = maxiter * (len(params) + 1) * 5  # a numeric gradient costs n + 1 evaluations
        for i, x0 in enumerate(starts(params, n_starts)):
            r = optimize.minimize(
                objective,
                x0,
                method="L-BFGS-B",
                bounds=list(zip(lo, hi, strict=True)),
                options={"maxiter": maxiter, "maxfun": maxfun},
            )
            runs.append(
                {
                    "start": i,
                    "objective": float(r.fun),
                    "iterations": int(r.nit),
                    "evaluations": int(r.nfev),
                    "converged": bool(r.success),
                    "message": str(r.message),
                    "x": r.x,
                }
            )
        best = min(runs, key=lambda r_: r_["objective"])
        vals = _decommon(params, _to_vals(params, best["x"]), model.names)
    else:
        best, vals = None, []
    plan = realize(spec, vals)
    after = model.predict(plan)
    out: Json = {
        "params": [
            {"stem": p["stem"], "param": p["param"], "kind": p["kind"], "value": v, "bounds": [p["lo"], p["hi"]]}
            for p, v in zip(params, vals, strict=True)
        ],
        "plan": plan,
        "objective": {
            "before": data_term(model.gains({})),
            "after": obj_vals(vals) if params else None,
            "alpha": alpha,
            "beta": beta,
            "weights": {t[0]: t[1] for t in terms},
        },
        "converged": bool(best["converged"]) if best else True,
        "starts": [{k: v for k, v in r_.items() if k != "x"} for r_ in runs],
        "unreachable": {w: u for w, u in unreachable.items() if u},
        "windows": {},
        "model_check": model.check(),
        "skipped": model.skipped,
        "trimmed_s": model.trimmed_s,
        "note": "powers add: correlation between stems is ignored (see model_check)",
    }
    for w in model.windows:
        tw = targets.get("windows", {}).get(w)
        if not tw:
            continue
        b, a = _compare(before[w], tw), _compare(after[w], tw)
        out["windows"][w] = {
            "lufs_before": before[w]["lufs"],
            "lufs_after": after[w]["lufs"],
            "lufs_change_lu": after[w]["lufs"] - before[w]["lufs"],
            "before": b,
            "after": a,
        }
    if measure and stems is not None:
        out["measured"] = measured_check(model, stems, plan, wins, bar_s)
    return out
