"""Synthetic "dum" takes of a reference song, to check pilot.py against a known answer.

    python3 -m transcriber.synth_takes jingle_bells_chorus /tmp/synth
    python3 -m transcriber.pilot /tmp/synth

Writes one free take (no click, 92 BPM) and three click takes (100 BPM, click
mixed in as a speaker would put it into the microphone). The truth is set
here: sung two semitones up, 15 cents flat, 30 ms behind the click, 15 ms
onset jitter and 20 cents pitch jitter per note on click takes (40 ms and
25 cents on the free take). Each note is a harmonic tone with a short
low-passed noise burst at its start, standing in for the "d".

On 24 September 2026 pilot.py read these as: transposition exact, tempo
exact, tuning -9 to -14 cents, asynchrony 18 ms (12 ms early), 50 or 51 of
51 notes, take-to-take agreement 0.91 to 0.96. With perfect detection the
jitter alone would allow about 0.98, so the pipeline costs a few points.
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from .pilot import HERE

SR = 44100


def take(ref, click, bpm, transpose, tuning_c, lag, jitter_ms, cents_sd, seed):
    r = np.random.default_rng(seed)
    spb = 60 / bpm
    beats = np.cumsum([0] + [n["beats"] for n in ref])
    T = beats[-1] * spb + 2.0
    y = np.zeros(int(T * SR))
    start = 1.0
    for n, b, d in zip(ref, beats[:-1], np.diff(beats)):
        t0 = start + b * spb + lag + r.normal(0, jitter_ms / 1000)
        dur = d * spb * 0.85
        f = 440 * 2 ** ((n["pitch"] + transpose + tuning_c / 100 + r.normal(0, cents_sd / 100) - 69) / 12)
        tt = np.arange(int(dur * SR)) / SR
        env = np.minimum(1, tt / 0.02) * np.exp(-tt * 0.8) * np.minimum(1, (dur - tt) / 0.03)
        tone = sum(a * np.sin(2 * np.pi * f * k * tt) for k, a in [(1, 1), (2, .5), (3, .3), (4, .15)]) * env * 0.3
        burst = np.convolve(r.normal(0, 1, int(0.015 * SR)) * np.hanning(int(0.015 * SR)) * 0.2, np.ones(8) / 8, "same")
        i = int(t0 * SR)
        y[i:i + len(tone)] += tone
        y[i:i + len(burst)] += burst
    if click:
        k = 0
        while start + k * spb < T - 0.2:
            i = int((start + k * spb) * SR)
            y[i:i + int(0.004 * SR)] += r.normal(0, 1, int(0.004 * SR)) * 0.25
            k += 1
    return y + r.normal(0, 0.002, len(y))


def main():
    song, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    ref = json.loads((HERE / "refs" / f"{song}.json").read_text())["notes"]
    sf.write(out / f"{song}_free.wav", take(ref, False, 92, 2, -15, 0.0, 40, 25, 1), SR)
    for s in (1, 2, 3):
        sf.write(out / f"{song}_click_{s}.wav", take(ref, True, 100, 2, -15, 0.03, 15, 20, 10 + s), SR)


if __name__ == "__main__":
    main()
