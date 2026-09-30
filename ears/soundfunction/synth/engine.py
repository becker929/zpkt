"""
Dependency-light synthesis engine for modern hard-techno test sounds.

Only numpy + scipy(.signal) are used for DSP; soundfile is used only by
callers (sweeps.py / presets.py) to write WAV files, never inside this
module. Every function is a pure function of its arguments (plus a fixed
default `seed` for the handful of functions that need noise), so calling
the same function with the same arguments always returns bit-identical
output -- this is what "deterministic / reproducible" means for this
engine: no wall-clock, no global RNG state, no I/O.

Sample rate is fixed at 44100 Hz, mono float32 in [-1, 1].
"""

import numpy as np
from scipy import signal as _sig

SR = 44100
_LN1000 = np.log(1000.0)  # so exp_env reaches -60 dB at t == decay_ms


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def exp_env(n, decay_ms, sr=SR):
    """Exponential decay envelope, 1.0 at t=0, -60 dB at t=decay_ms."""
    t = np.arange(n) / sr
    tau = max(decay_ms, 1e-6) / 1000.0 / _LN1000
    return np.exp(-t / tau)


def softclip(x, drive=0.5):
    """Tanh soft-clip. drive in [0, ~1+] maps to increasing saturation."""
    if drive <= 0:
        return x
    k = 1.0 + drive * 9.0
    return np.tanh(x * k) / np.tanh(k)


def _nyq_clip(hz, sr=SR, frac=0.49):
    return float(np.clip(hz, 1.0, sr * frac))


def one_pole_lowpass(x, cutoff_hz, sr=SR):
    """Single-pole IIR lowpass (gentle, phase-y, good for envelopes/tails)."""
    cutoff_hz = _nyq_clip(cutoff_hz, sr)
    a = np.exp(-2 * np.pi * cutoff_hz / sr)
    return _sig.lfilter([1 - a], [1, -a], x)


def butter_filter(x, cutoff, sr=SR, btype="low", order=4):
    """Butterworth filter via SOS. `cutoff` is a scalar or [lo, hi] pair."""
    if btype == "band":
        lo, hi = cutoff
        cutoff = [_nyq_clip(lo, sr), _nyq_clip(hi, sr, frac=0.499)]
        if cutoff[1] <= cutoff[0]:
            cutoff[1] = cutoff[0] + 1.0
    else:
        cutoff = _nyq_clip(cutoff, sr)
    sos = _sig.butter(order, cutoff, btype=btype, fs=sr, output="sos")
    return _sig.sosfilt(sos, x)


def normalize(x, peak_db=-1.0):
    peak = np.max(np.abs(x)) + 1e-12
    target = 10 ** (peak_db / 20.0)
    return x * (target / peak)


def mix(*tracks):
    """Sum tracks (zero-padded to the longest) with simple peak protection."""
    tracks = [np.asarray(t, dtype=np.float64) for t in tracks if len(t) > 0]
    if not tracks:
        return np.zeros(0, dtype=np.float32)
    n = max(len(t) for t in tracks)
    out = np.zeros(n, dtype=np.float64)
    for t in tracks:
        out[: len(t)] += t
    peak = np.max(np.abs(out))
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32)


def _comb(x, delay_s, decay_ms, sr=SR):
    """Single feedback comb resonator: y[n] = x[n] + fb*y[n-d]."""
    d = max(int(delay_s * sr), 1)
    fb = 0.001 ** (d / (decay_ms / 1000.0 * sr))
    fb = float(np.clip(fb, 0.0, 0.995))
    a_coef = np.zeros(d + 1)
    a_coef[0] = 1.0
    a_coef[d] = -fb
    return _sig.lfilter([1.0], a_coef, x)


def _reverb_tail(x, decay_ms, sr=SR, delays=(0.0233, 0.0299, 0.0367, 0.0419)):
    """Reverb-like feedback delay network: parallel combs, averaged."""
    tail_len = len(x) + int(decay_ms / 1000.0 * sr)
    xp = np.zeros(tail_len)
    xp[: len(x)] = x
    combs = [_comb(xp, d, decay_ms, sr) for d in delays]
    return np.mean(combs, axis=0)


def _ms(n_ms, sr=SR):
    return int(round(n_ms / 1000.0 * sr))


# --------------------------------------------------------------------------
# Sound sources
# --------------------------------------------------------------------------

def kick(pitch_start_hz=180, pitch_end_hz=45, pitch_decay_ms=35,
         amp_decay_ms=300, click_ms=3, click_level=0.5, drive=0.6,
         length_ms=450, sr=SR, seed=0):
    """Punchy, distorted hard-techno kick: sine sweep + transient click.

    Models the KICK -- the pulse / metronome of the track.
    """
    n = _ms(length_ms, sr)
    pitch_env = exp_env(n, pitch_decay_ms, sr)
    freq = pitch_end_hz + (pitch_start_hz - pitch_end_hz) * pitch_env
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = np.sin(phase) * exp_env(n, amp_decay_ms, sr)

    click = np.zeros(n)
    cn = min(_ms(click_ms, sr), n)
    if cn > 0 and click_level > 0:
        rng = np.random.default_rng(seed)
        noise = rng.uniform(-1, 1, cn)
        click[:cn] = noise * exp_env(cn, max(click_ms / 3.0, 0.3), sr) * click_level

    sig_out = softclip(body + click, drive)
    return normalize(sig_out, -1.0).astype(np.float32)


def rumble(kick_array, decay_ms=900, lowpass_hz=160, drive=0.4,
           sidechain_ms=120, sr=SR):
    """Sub-weight tail fed from the kick through a feedback delay network.

    Models the RUMBLE -- sustained sub-bass weight under the kick. Returns
    the processed tail ALONE (the dry kick is not included), front-ducked
    so it tucks in under the kick's transient (a static sidechain shape).
    """
    kick_array = np.asarray(kick_array, dtype=np.float64)
    src = butter_filter(kick_array, lowpass_hz * 1.5, sr, "low")
    tail = _reverb_tail(src, decay_ms, sr)
    tail = butter_filter(tail, lowpass_hz, sr, "low")
    tail = softclip(tail, drive)

    duck_n = min(_ms(sidechain_ms, sr), len(tail))
    if duck_n > 0:
        env = np.ones(len(tail))
        env[:duck_n] = np.linspace(0.05, 1.0, duck_n) ** 2
        tail = tail * env
    return normalize(tail, -3.0).astype(np.float32)


def hat(closed=True, decay_ms=None, highpass_hz=6000, tone=0.3, level=0.5,
        sr=SR, seed=1):
    """Filtered noise + detuned-square metallic burst.

    Models the HAT -- subdivision / rhythmic drive (closed) or the lift of
    an open accent (open).
    """
    if decay_ms is None:
        decay_ms = 40 if closed else 220
    n = max(_ms(decay_ms * 4, sr), 32)
    t = np.arange(n) / sr

    rng = np.random.default_rng(seed)
    noise = rng.uniform(-1, 1, n)

    ratios = (1.0, 1.342, 1.732, 2.253, 2.981, 3.414)  # inharmonic, hi-hat-like
    base_freq = 300.0
    metallic = np.mean([_sig.square(2 * np.pi * base_freq * r * t) for r in ratios], axis=0)

    mixed = (1 - tone) * noise + tone * metallic
    mixed = mixed * exp_env(n, decay_ms, sr)
    mixed = butter_filter(mixed, highpass_hz, sr, "high")
    return (normalize(mixed, -2.0) * level).astype(np.float32)


def clap(decay_ms=180, bursts=3, burst_gap_ms=10, bandpass_lo=900,
         bandpass_hi=3500, tail_ms=120, sr=SR, seed=2, burst_decay=1.0, tail_from_first=False):
    """Stacked noise bursts (the 'flam') plus a bandpassed decaying tail.

    Models the CLAP -- the backbeat accent.

    burst_decay < 1 makes each later burst quieter than the one before, and
    tail_from_first starts the tail under the first burst: together they put
    the loudest moment at the very start, which is how real claps measure
    (rise time ~3 ms, not ~50 ms). Defaults keep the part-one sound.
    """
    rng = np.random.default_rng(seed)
    burst_n = _ms(8, sr)
    gap_n = _ms(burst_gap_ms, sr)
    bursts = max(bursts, 1)
    tail_n = _ms(decay_ms + tail_ms, sr)
    burst_span = bursts * burst_n + (bursts - 1) * gap_n
    n = burst_span + tail_n

    sig_out = np.zeros(n)
    pos = 0
    for k in range(bursts):
        b = rng.uniform(-1, 1, burst_n) * exp_env(burst_n, 4.0, sr) * (burst_decay ** k)
        sig_out[pos:pos + burst_n] += b
        pos += burst_n + gap_n

    tail_start = 0 if tail_from_first else max(pos - gap_n, 0)
    tail_noise = rng.uniform(-1, 1, n - tail_start)
    sig_out[tail_start:] += tail_noise * exp_env(len(tail_noise), decay_ms, sr)

    sig_out = butter_filter(sig_out, [bandpass_lo, bandpass_hi], sr, "band")
    return normalize(sig_out, -1.0).astype(np.float32)


def ride_or_perc(pitch_hz=800, decay_ms=120, noise_mix=0.5, highpass_hz=2500,
                  sr=SR, seed=3):
    """Short metallic/tonal hit: inharmonic tone stack blended with noise.

    Models RIDE / PERCUSSION -- ticking texture / groove ornamentation.
    """
    n = max(_ms(decay_ms * 3, sr), 64)
    t = np.arange(n) / sr
    tone = (np.sin(2 * np.pi * pitch_hz * t)
            + 0.5 * np.sin(2 * np.pi * pitch_hz * 2.4 * t)
            + 0.3 * np.sin(2 * np.pi * pitch_hz * 3.8 * t)) / 1.8

    rng = np.random.default_rng(seed)
    noise = rng.uniform(-1, 1, n)

    sig_out = (1 - noise_mix) * tone + noise_mix * noise
    sig_out = sig_out * exp_env(n, decay_ms, sr)
    sig_out = butter_filter(sig_out, highpass_hz, sr, "high")
    return normalize(sig_out, -1.5).astype(np.float32)


def stab(freq_hz=110, wave="saw", detune_cents=12, voices=3, attack_ms=2,
          decay_ms=250, cutoff_hz=1800, drive=0.7, sr=SR):
    """Detuned unison saw/square stab through a lowpass and soft-clip drive.

    Models the STAB / LEAD -- the melodic hook.
    """
    n = max(_ms(decay_ms * 1.2, sr), _ms(attack_ms, sr) + 32)
    t = np.arange(n) / sr

    sig_out = np.zeros(n)
    for v in range(voices):
        cents = 0.0 if voices == 1 else detune_cents * ((v / (voices - 1)) * 2 - 1)
        f = freq_hz * (2 ** (cents / 1200.0))
        phase = f * t
        if wave == "saw":
            osc = 2 * (phase - np.floor(phase + 0.5))
        elif wave == "square":
            osc = _sig.square(2 * np.pi * phase)
        else:
            osc = np.sin(2 * np.pi * phase)
        sig_out += osc
    sig_out /= voices

    env = exp_env(n, decay_ms, sr)
    an = max(_ms(attack_ms, sr), 1)
    env[:an] *= np.linspace(0, 1, an)
    sig_out *= env

    sig_out = butter_filter(sig_out, cutoff_hz, sr, "low")
    sig_out = softclip(sig_out, drive)
    return normalize(sig_out, -1.0).astype(np.float32)


def pad(freq_hz=55, harmonics=(1, 2, 3, 5), attack_ms=400, length_ms=4000,
        lowpass_hz=900, sr=SR):
    """Slow additive pad with a raised-cosine attack/release.

    Models the PAD -- ambient space / harmonic bed (breakdowns).
    """
    n = _ms(length_ms, sr)
    t = np.arange(n) / sr
    sig_out = np.zeros(n)
    for h in harmonics:
        sig_out += np.sin(2 * np.pi * freq_hz * h * t) / h
    sig_out /= len(harmonics)

    an = max(_ms(attack_ms, sr), 1)
    rn = max(min(_ms(length_ms * 0.25, sr), n - an), 1)
    env = np.ones(n)
    env[:an] = 0.5 - 0.5 * np.cos(np.pi * np.arange(an) / an)
    env[-rn:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(rn) / rn)
    sig_out *= env

    sig_out = butter_filter(sig_out, lowpass_hz, sr, "low")
    return normalize(sig_out, -3.0).astype(np.float32)


def riser(length_ms=8000, start_hz=200, end_hz=8000, noise_mix=0.8, sr=SR,
          seed=4):
    """Exponential up-sweep tone blended with brightening noise, rising amp.

    Models the RISER -- a transition-building tension element.
    """
    n = _ms(length_ms, sr)
    t = np.arange(n) / sr
    dur = length_ms / 1000.0

    ratio = end_hz / start_hz
    freq = start_hz * (ratio ** (t / dur))
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase)

    rng = np.random.default_rng(seed)
    noise = rng.uniform(-1, 1, n)
    noise_lo = butter_filter(noise, start_hz, sr, "high")
    noise_hi = butter_filter(noise, end_hz * 0.5, sr, "high")
    blend = t / dur
    noise_shaped = noise_lo * (1 - blend) + noise_hi * blend

    sig_out = (1 - noise_mix) * tone + noise_mix * noise_shaped
    amp_env = (t / dur) ** 2
    sig_out *= amp_env
    return normalize(sig_out, -1.0).astype(np.float32)


def impact(length_ms=1500, boom_hz=40, noise_ms=80, reverb_ms=1200, sr=SR,
           seed=5):
    """Low boom + noise splash with a long comb-reverb tail.

    Models the IMPACT -- a hard transition marker (drop-in hit).
    """
    n = _ms(length_ms, sr)
    t = np.arange(n) / sr
    boom = np.sin(2 * np.pi * boom_hz * t) * exp_env(n, length_ms * 0.6, sr)

    rng = np.random.default_rng(seed)
    nn = min(_ms(noise_ms, sr), n)
    noise = np.zeros(n)
    noise[:nn] = rng.uniform(-1, 1, nn) * exp_env(nn, max(noise_ms / 2.0, 1), sr)

    src = boom + noise
    tail = _reverb_tail(src, reverb_ms, sr) * 0.6
    sig_out = tail
    sig_out[:n] += src
    sig_out = softclip(sig_out, 0.3)
    return normalize(sig_out, -1.0).astype(np.float32)


# --------------------------------------------------------------------------
# Sequencer
# --------------------------------------------------------------------------

def _step_vel(step):
    if isinstance(step, (tuple, list)):
        return step[0], step[1]
    return step, 1.0


def loop(bpm, bars, steps_per_bar=16, tracks=None, sidechain=None, sr=SR):
    """Place hits on a 16th-note grid.

    tracks: {name: (array, [step_index or (step_index, velocity), ...])}
    sidechain: {target_track: (source_track, ducking_ms)} -- ducks the
        target track's stem around every hit of the source track.

    Returns (mixed_loop, stems) where stems is {name: np.float32 array}.
    """
    tracks = tracks or {}
    beat_dur = 60.0 / bpm
    step_dur = beat_dur / (steps_per_bar / 4.0)
    total_steps = steps_per_bar * bars
    tail_pad = max((len(a) for a, _ in tracks.values()), default=0)
    total_len = int(total_steps * step_dur * sr) + tail_pad

    stems = {}
    for name, (arr, steps) in tracks.items():
        stem = np.zeros(total_len)
        for step in steps:
            idx, vel = _step_vel(step)
            for b in range(bars):
                pos = int((b * steps_per_bar + idx) * step_dur * sr)
                end = min(pos + len(arr), total_len)
                if end > pos:
                    stem[pos:end] += arr[: end - pos] * vel
        stems[name] = stem

    if sidechain:
        for target, (source, duck_ms) in sidechain.items():
            if target not in stems or source not in tracks:
                continue
            _, src_steps = tracks[source]
            env = np.ones(total_len)
            duck_n = _ms(duck_ms, sr)
            for step in src_steps:
                idx, _ = _step_vel(step)
                for b in range(bars):
                    pos = int((b * steps_per_bar + idx) * step_dur * sr)
                    seg = min(duck_n, total_len - pos)
                    if seg > 0:
                        env[pos:pos + seg] = np.minimum(
                            env[pos:pos + seg], np.linspace(0.1, 1.0, seg) ** 2)
            stems[target] = stems[target] * env

    stems = {k: v.astype(np.float32) for k, v in stems.items()}
    mixed = mix(*stems.values()) if stems else np.zeros(total_len, dtype=np.float32)
    return mixed, stems
