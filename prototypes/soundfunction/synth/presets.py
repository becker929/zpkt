"""
Canonical modern hard-techno one-bar (or four-bar) patterns built from
synth.engine sounds, used as realistic composite test material.
"""

import numpy as np

from . import engine
from .engine import SR


def _steady_hats(hat_snd, stem, steps, step_dur, sr, steps_per_bar, bars):
    for step in steps:
        for b in range(bars):
            pos = int((b * steps_per_bar + step) * step_dur * sr)
            end = min(pos + len(hat_snd), len(stem))
            if end > pos:
                stem[pos:end] += hat_snd[: end - pos]


def _buildup(bpm, sr=SR):
    """4 bars: a riser under a snare/clap roll that doubles every bar."""
    steps_per_bar = 16
    bars = 4
    step_dur = (60.0 / bpm) / (steps_per_bar / 4.0)
    bar_len = int(steps_per_bar * step_dur * sr)

    riser_snd = engine.riser(length_ms=bar_len * bars / sr * 1000.0,
                              start_hz=150, end_hz=6000, noise_mix=0.7)
    clap_snd = engine.clap(decay_ms=140)
    hat_snd = engine.hat(closed=True)

    total_len = bar_len * bars + max(len(riser_snd), len(clap_snd), len(hat_snd))
    riser_stem = np.zeros(total_len)
    riser_stem[: len(riser_snd)] = riser_snd
    clap_stem = np.zeros(total_len)
    hat_stem = np.zeros(total_len)

    # snare/clap roll doubling in density each bar: 1, 2, 4, 8 hits
    patterns = [[12], [8, 12], [4, 8, 12, 14], [0, 2, 4, 6, 8, 10, 12, 14]]
    for bar, steps in enumerate(patterns):
        for step in steps:
            pos = int((bar * steps_per_bar + step) * step_dur * sr)
            end = min(pos + len(clap_snd), total_len)
            if end > pos:
                clap_stem[pos:end] += clap_snd[: end - pos]

    _steady_hats(hat_snd, hat_stem, [2, 6, 10, 14], step_dur, sr, steps_per_bar, bars)

    stems = {
        "riser": riser_stem.astype(np.float32),
        "clap": clap_stem.astype(np.float32),
        "hat_closed": hat_stem.astype(np.float32),
    }
    mixed = engine.normalize(engine.mix(*stems.values()), -1.0)
    return mixed, stems


def hard_techno_bar(bpm=150, variant="core", sr=SR):
    """Return (mixed_loop, stems) for one canonical hard-techno bar.

    variant: 'core' (kick+rumble+hats+clap), 'full' (+stab, perc),
             'drop' (everything, denser hats, ride), 'breakdown'
             (pad + hats, no kick), 'buildup' (4-bar riser + roll).
    """
    if variant == "buildup":
        return _buildup(bpm, sr)

    kick_snd = engine.kick()
    rumble_snd = engine.rumble(kick_snd)
    hat_c = engine.hat(closed=True)
    hat_o = engine.hat(closed=False)
    clap_snd = engine.clap()
    stab_snd = engine.stab()
    perc_snd = engine.ride_or_perc(pitch_hz=1200, decay_ms=90, noise_mix=0.6)
    ride_snd = engine.ride_or_perc(pitch_hz=600, decay_ms=150, noise_mix=0.3)

    if variant == "breakdown":
        step_dur = (60.0 / bpm) / (16 / 4.0)
        bar_ms = 16 * step_dur * 1000.0
        pad_snd = engine.pad(length_ms=bar_ms, lowpass_hz=900)
        tracks = {
            "pad": (pad_snd, [0]),
            "hat_closed": (hat_c, [2, 6, 10, 14]),
        }
        sidechain = None
    else:
        tracks = {
            "kick": (kick_snd, [0, 4, 8, 12]),
            "rumble": (rumble_snd, [0, 4, 8, 12]),
            "hat_closed": (hat_c, [2, 6, 10, 14]),
            "hat_open": (hat_o, [6, 14]),
            "clap": (clap_snd, [4, 12]),
        }
        sidechain = {"rumble": ("kick", 120)}
        if variant in ("full", "drop"):
            tracks["stab"] = (stab_snd, [10])
            tracks["perc"] = (perc_snd, [3, 7, 11, 15])
        if variant == "drop":
            tracks["hat_closed"] = (hat_c, [
                (2, 1.0), (6, 1.0), (10, 1.0), (14, 1.0),
                (1, 0.5), (3, 0.5), (5, 0.5), (7, 0.5),
                (9, 0.5), (11, 0.5), (13, 0.5), (15, 0.5),
            ])
            tracks["ride"] = (ride_snd, [0, 8])

    mixed, stems = engine.loop(bpm, 1, steps_per_bar=16, tracks=tracks,
                                sidechain=sidechain, sr=sr)
    mixed = engine.normalize(mixed, -1.0)
    return mixed, stems
