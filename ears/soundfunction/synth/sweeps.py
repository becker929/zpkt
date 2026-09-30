"""
Parameter sweeps + preset-loop rendering for the hard-techno test engine.

Run from /home/user/sound-function with:
    python3 -m synth.sweeps
"""

import os

import soundfile as sf

from . import engine, presets
from .engine import SR

SWEEP_DIR = "/home/user/sound-function/out/sweeps"
LOOP_DIR = "/home/user/sound-function/out/loops"


def sweep(sound_fn, param, values, **fixed):
    """Render one sound per value of `param`, holding `fixed` constant.

    Returns [(value, array), ...].
    """
    results = []
    for v in values:
        kwargs = dict(fixed)
        kwargs[param] = v
        results.append((v, sound_fn(**kwargs)))
    return results


def _sweep_specs():
    kick0 = engine.kick()
    return [
        ("kick", engine.kick, "pitch_end_hz", [35, 45, 55, 70, 90], {}),
        ("kick", engine.kick, "amp_decay_ms", [120, 200, 300, 450, 700], {}),
        ("kick", engine.kick, "drive", [0, 0.3, 0.6, 0.9], {}),
        ("kick", engine.kick, "click_level", [0, 0.25, 0.5, 1.0], {}),
        ("hat", engine.hat, "decay_ms", [15, 30, 60, 120, 250], {}),
        ("hat", engine.hat, "highpass_hz", [3000, 5000, 7000, 9000], {}),
        ("hat", engine.hat, "tone", [0, 0.3, 0.6, 1.0], {}),
        ("clap", engine.clap, "decay_ms", [80, 140, 200, 300], {}),
        ("clap", engine.clap, "bursts", [1, 2, 3, 4], {}),
        ("stab", engine.stab, "cutoff_hz", [600, 1200, 2400, 4800], {}),
        ("stab", engine.stab, "decay_ms", [60, 150, 300, 600], {}),
        ("stab", engine.stab, "drive", [0, 0.4, 0.8], {}),
        ("rumble", engine.rumble, "decay_ms", [300, 600, 900, 1500], {"kick_array": kick0}),
        ("rumble", engine.rumble, "lowpass_hz", [90, 130, 180, 260], {"kick_array": kick0}),
    ]


def render_sweeps(out_dir=SWEEP_DIR):
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for name, fn, param, values, fixed in _sweep_specs():
        for value, arr in sweep(fn, param, values, **fixed):
            path = os.path.join(out_dir, f"{name}__{param}__{value}.wav")
            sf.write(path, arr, SR)
            count += 1
    return count


def render_presets(out_dir=LOOP_DIR):
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for variant in ("core", "full", "drop", "breakdown", "buildup"):
        mixed, stems = presets.hard_techno_bar(bpm=150, variant=variant)
        sf.write(os.path.join(out_dir, f"{variant}.wav"), mixed, SR)
        count += 1
        for name, stem in stems.items():
            sf.write(os.path.join(out_dir, f"{variant}__{name}.wav"), stem, SR)
            count += 1
    return count


def main():
    n_sweeps = render_sweeps()
    n_loops = render_presets()
    print(f"Wrote {n_sweeps} sweep WAV files to {SWEEP_DIR}")
    print(f"Wrote {n_loops} loop/stem WAV files to {LOOP_DIR}")


if __name__ == "__main__":
    main()
