"""Six mix alternates for HW002, each a small DSP chain over the group stems.

Stems (Live group outputs, the main bus is only a Utility so they sum to the mix):
kick (kick + rumble), perc (splash + hats), sfx, brk. Each aspect has normalised
params in [0, 1]; params all at their "neutral" value reproduce the original mix.
Bus levels are restored after processing, so an aspect changes tone, not balance.
"""
import numpy as np
import pedalboard as P
from scipy import signal

from mlab import loudness as L

SR = 44100


def _pb(board, x, sr):
    return board(x.T.astype(np.float32), sr).T.astype(np.float64)


def _match_rms(y, ref):
    a, b = np.sqrt(np.mean(y ** 2)), np.sqrt(np.mean(ref ** 2))
    return y * (b / a) if a > 0 else y


def _split(x, sr, f):
    """Zero-phase crossover: low + high == x exactly."""
    sos = signal.butter(4, f, "low", fs=sr, output="sos")
    lo = signal.sosfiltfilt(sos, x, axis=0)
    return lo, x - lo


def _ms(x):
    return (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2


def _lr(m, s):
    return np.stack([m + s, m - s], axis=1)


def _lin(u, lo, hi):
    return lo + (hi - lo) * u


def _log(u, lo, hi):
    return lo * (hi / lo) ** u


# ---------------------------------------------------------------- aspects
def kick_distortion(st, sr, u):
    """Kick bus, mid only, clean sub: above a crossover, pre-emphasis bell -> tanh drive -> tone low-pass, blended."""
    f, g, drive, tone, mix = _log(u[0], 500, 4000), _lin(u[1], 0, 12), _lin(u[2], 0, 30), _log(u[3], 3000, 18000), u[4]
    xo = _log(u[5], 60, 250)
    k = st["kick"]
    m, s = _ms(k)                      # mid only: per-channel drive decorrelates the low end
    lo, hi = _split(m[:, None], sr, xo)   # keep the sub clean below the crossover
    lo, hi = lo[:, 0], hi[:, 0]
    wet = _pb(P.Pedalboard([P.PeakFilter(f, g, 0.8), P.Distortion(drive), P.LowpassFilter(tone)]), hi[:, None], sr)[:, 0]
    m2 = lo + (1 - mix) * hi + mix * _match_rms(wet, hi)
    y = _match_rms(_lr(m2, s), k)
    return {**st, "kick": y}, {"emphasis_hz": f, "emphasis_db": g, "drive_db": drive, "tone_lowpass_hz": tone, "mix": mix,
                               "clean_below_hz": xo}


def colour(st, sr, u):
    """Mix EQ: lift the mids, trim the 80-200 Hz bump, tame the air."""
    fm, gm, qm = _log(u[0], 500, 4000), _lin(u[1], 0, 10), _log(u[2], 0.3, 2)
    fl, gl, ql = _log(u[3], 60, 250), _lin(u[4], -6, 0), _log(u[5], 0.5, 2)
    fh, gh = _log(u[6], 4000, 14000), _lin(u[7], -10, 0)
    board = P.Pedalboard([P.PeakFilter(fm, gm, qm), P.PeakFilter(fl, gl, ql), P.HighShelfFilter(fh, gh, 0.7)])
    return {"mix_post": board}, {"mid_hz": fm, "mid_db": gm, "mid_q": qm, "lowmid_hz": fl, "lowmid_db": gl,
                                  "lowmid_q": ql, "air_shelf_hz": fh, "air_db": gh}


def deep_sub(st, sr, u):
    """Kick bus: bring back 25-40 Hz under the kick's low cut."""
    f1, g1, q1 = _log(u[0], 22, 50), _lin(u[1], 0, 15), _log(u[2], 0.5, 2)
    fs, gs = _log(u[3], 30, 90), _lin(u[4], -6, 0)
    k = st["kick"]
    y = _pb(P.Pedalboard([P.PeakFilter(f1, g1, q1), P.PeakFilter(fs * 2.5, gs, 1.0)]), k, sr)
    return {**st, "kick": y}, {"sub_hz": f1, "sub_db": g1, "sub_q": q1, "upper_bass_hz": fs * 2.5, "upper_bass_db": gs}


def mono_low(st, sr, u):
    """Mix M/S: turn the side signal down below a crossover."""
    f, g = _log(u[0], 50, 300), _lin(u[1], -60, 0)
    return {"mix_ms": (f, g)}, {"crossover_hz": f, "side_below_db": g}


def density(st, sr, u):
    """Drum bus (kick + perc), mid only: soft clip plus parallel compression, level restored."""
    drive, thr, ratio = _lin(u[0], 0, 15), _lin(u[1], -40, -10), _lin(u[2], 2, 12)
    att, rel, mix = _log(u[3], 0.5, 30), _log(u[4], 30, 300), _lin(u[5], 0, 0.8)
    bus = st["kick"] + st["perc"]
    m, s = _ms(bus)                    # mid only, side untouched (as with the kick distortion)
    clip = np.tanh(m * 10 ** (drive / 20)) / max(np.tanh(10 ** (drive / 20)), 1e-6) if drive > 0.01 else m
    clip = _match_rms(clip, m)
    comp = _match_rms(_pb(P.Pedalboard([P.Compressor(thr, ratio, att, rel)]), clip[:, None], sr)[:, 0], clip)
    y = _match_rms(_lr(_match_rms((1 - mix) * clip + mix * comp, m), s), bus)
    return {**st, "drumbus": y}, {
        "clip_drive_db": drive, "comp_threshold_db": thr, "comp_ratio": ratio, "comp_attack_ms": att,
        "comp_release_ms": rel, "parallel_mix": mix}


def space(st, sr, u):
    """Perc bus: reverb send plus wider highs."""
    room, damp, wet = _lin(u[0], 0.1, 0.95), _lin(u[1], 0, 1), _lin(u[2], 0, 0.5)
    f, sg = _log(u[3], 500, 4000), _lin(u[4], 0, 9)
    p = st["perc"]
    y = _pb(P.Pedalboard([P.Reverb(room_size=room, damping=damp, wet_level=wet, dry_level=1.0, width=1.0)]), p, sr)
    lo, hi = _split(y, sr, f)
    m, s = _ms(hi)
    y = lo + _lr(m, s * 10 ** (sg / 20))
    return {**st, "perc": _match_rms(y, p)}, {"room_size": room, "damping": damp, "reverb_wet": wet,
                                              "widen_above_hz": f, "side_lift_db": sg}


ASPECTS = {
    # name: (fn, n_params, neutral params, spoken name)
    "kick_distortion": (kick_distortion, 6, [0.5, 0, 0, 1, 0, 0.5], "Kick distortion"),
    "colour": (colour, 8, [0.5, 0, 0.5, 0.5, 1, 0.5, 0.5, 1], "Colour"),
    "deep_sub": (deep_sub, 5, [0.3, 0, 0.5, 0.5, 1], "Deep sub"),
    "mono_low": (mono_low, 2, [0.5, 1], "Mono low end"),
    "density": (density, 6, [0, 1, 0, 0.5, 0.5, 0], "Drop power"),
    "space": (space, 5, [0.5, 0.5, 0, 0.5, 0], "Space"),
}


def mixdown(st, sr, extra=()):
    """Sum stems, then apply mix-level effects in a fixed order."""
    drum = st.get("drumbus")
    y = (drum if drum is not None else st["kick"] + st["perc"]) + st["sfx"] + st["brk"]
    for fx in extra:
        if "mix_post" in fx:
            y = _pb(fx["mix_post"], y, sr)
        if "mix_ms" in fx:
            f, g = fx["mix_ms"]
            m, s = _ms(y)
            slo, shi = _split(s[:, None], sr, f)
            y = _lr(m, shi[:, 0] + slo[:, 0] * 10 ** (g / 20))
    return y


def render(stems, sr, choices):
    """choices: {aspect: u}. Stem aspects first, drum bus next, mix aspects last."""
    st = dict(stems)
    mix_fx = []
    for name in ("deep_sub", "kick_distortion", "space", "density", "colour", "mono_low"):
        if name in choices:
            res, _ = ASPECTS[name][0](st, sr, choices[name])
            if "mix_post" in res or "mix_ms" in res:
                mix_fx.append(res)
            else:
                st = res
    return mixdown(st, sr, mix_fx)


def describe(name, u, sr=SR):
    stub = {"kick": np.zeros((16, 2)), "perc": np.zeros((16, 2)), "sfx": np.zeros((16, 2)), "brk": np.zeros((16, 2))}
    return ASPECTS[name][0](stub, sr, u)[1]
