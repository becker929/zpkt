"""Stage 1: a labelled library of synthetic single hits.

    python3 -m synth.library            -> library/synth/wav/<role>__lib__<nnnn>.wav + manifest.csv

Forty hits per role, each with every synth setting drawn at random from a
range wide enough to cover how the role is actually made in hard techno,
but not so wide that the sound stops being that role. The ranges are the
labels' definition, so they are written out here, not hidden in code paths.
The seed is fixed: the library is reproducible byte for byte.
"""
import csv, os
import numpy as np, soundfile as sf
from synth import engine as E

PER_ROLE = 40
OUT = "library/synth"

def _u(rng, lo, hi): return float(rng.uniform(lo, hi))
def _lu(rng, lo, hi): return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))

V2 = False   # set by --v2: ranges corrected after part two's synthetic-vs-real comparison


def make(role, rng, i):
    """Return (audio, settings) for one random example of a role."""
    if role == "kick":
        p = dict(pitch_start_hz=_lu(rng, 110, 300), pitch_end_hz=_u(rng, 35, 62), pitch_decay_ms=_lu(rng, 12, 80),
                 amp_decay_ms=_lu(rng, 110, 750), click_ms=_u(rng, 0.5, 6), click_level=_u(rng, 0.0, 0.9),
                 drive=_u(rng, 0.0, 0.95), length_ms=500, seed=i)
        return E.kick(**p), p
    if role == "rumble":
        k = E.kick(pitch_end_hz=_u(rng, 38, 55), amp_decay_ms=_lu(rng, 150, 400), drive=_u(rng, 0.3, 0.9), seed=i)
        p = dict(decay_ms=_lu(rng, 400, 1600), lowpass_hz=_lu(rng, 90, 260), drive=_u(rng, 0.1, 0.85), sidechain_ms=_u(rng, 60, 200))
        return E.rumble(k, **p), p
    if role == "hat_closed":
        # v2: real closed hats ring longer than the pilot's (real hat median decay40 was 330 ms, ours 50)
        p = dict(closed=True, decay_ms=_lu(rng, 15, 180) if V2 else _lu(rng, 8, 70), highpass_hz=_lu(rng, 3500, 9500), tone=_u(rng, 0.0, 0.75), level=0.5, seed=i)
        return E.hat(**p), p
    if role == "hat_open":
        p = dict(closed=False, decay_ms=_lu(rng, 150, 800) if V2 else _lu(rng, 90, 450), highpass_hz=_lu(rng, 3000, 8500), tone=_u(rng, 0.0, 0.75), level=0.5, seed=i)
        return E.hat(**p), p
    if role == "clap":
        lo = _lu(rng, 450, 1500)
        p = dict(decay_ms=_lu(rng, 70, 320), bursts=int(rng.integers(1, 6)), burst_gap_ms=_u(rng, 6, 16),
                 bandpass_lo=lo, bandpass_hi=lo * _u(rng, 2.2, 5.0), tail_ms=_lu(rng, 30, 280), seed=i)
        if V2:   # real claps hit at once: loudest burst first, tail under it, tighter flam
            p.update(burst_gap_ms=_u(rng, 3, 10), burst_decay=_u(rng, 0.35, 0.8), tail_from_first=True, tail_ms=_lu(rng, 20, 160))
        return E.clap(**p), p
    if role == "perc":
        p = dict(pitch_hz=_lu(rng, 350, 2200), decay_ms=_lu(rng, 35, 220), noise_mix=_u(rng, 0.05, 0.95), highpass_hz=_lu(rng, 900, 4200), seed=i)
        return E.ride_or_perc(**p), p
    if role == "stab":
        p = dict(freq_hz=_lu(rng, 50, 230), wave=("saw", "square")[int(rng.integers(0, 2))], detune_cents=_u(rng, 0, 30),
                 voices=int(rng.integers(1, 6)), attack_ms=_lu(rng, 1, 15), decay_ms=_lu(rng, 90, 520),
                 cutoff_hz=_lu(rng, 700, 4500), drive=_u(rng, 0.1, 0.95))
        return E.stab(**p), p
    if role == "pad":
        p = dict(freq_hz=_lu(rng, 38, 120), attack_ms=_lu(rng, 120, 1000), length_ms=_u(rng, 2000, 5000), lowpass_hz=_lu(rng, 350, 2500),
                 harmonics=((1, 2, 3, 5), (1, 2, 4), (1, 3, 5, 7), (1, 2, 3, 4, 5, 6))[int(rng.integers(0, 4))])
        return E.pad(**p), p
    if role == "riser":
        s = _lu(rng, 80, 500)
        p = dict(length_ms=_u(rng, 1500, 8000), start_hz=s, end_hz=s * _lu(rng, 8, 60), noise_mix=_u(rng, 0.3, 1.0), seed=i)
        return E.riser(**p), p
    if role == "impact":
        p = dict(length_ms=_u(rng, 700, 2600), boom_hz=_u(rng, 32, 65), noise_ms=_lu(rng, 30, 180), reverb_ms=_lu(rng, 500, 2200), seed=i)
        return E.impact(**p), p
    raise ValueError(role)

ROLES = ["kick", "rumble", "hat_closed", "hat_open", "clap", "perc", "stab", "pad", "riser", "impact"]

def main(out=OUT, per_role=PER_ROLE):
    os.makedirs(f"{out}/wav", exist_ok=True)
    rows = []
    for r, role in enumerate(ROLES):
        rng = np.random.default_rng(1000 + r)
        for i in range(1, per_role + 1):
            y, p = make(role, rng, i)
            name = f"{role}__lib__{i:04d}.wav"
            sf.write(f"{out}/wav/{name}", E.normalize(y), E.SR, subtype="PCM_16")
            rows.append({"file": f"wav/{name}", "role": role, "settings": ";".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in p.items())})
    with open(f"{out}/manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "role", "settings"]); w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} hits to {out}")

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--v2" in args:
        V2 = True; args.remove("--v2")
    out = args[args.index("--out") + 1] if "--out" in args else (OUT + "2" if V2 else OUT)
    main(out=out)
