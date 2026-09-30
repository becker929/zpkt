# synth — hard-techno test-sound engine

Dependency-light (numpy + scipy.signal; soundfile only for writing WAVs),
deterministic (fixed seeds, no wall-clock) synthesis engine for generating
controlled test material for studying which measurable parameters determine
a sound's *structural role* in hard techno.

## What each function models

| Function        | Structural role       | What it models |
|-----------------|------------------------|-----------------|
| `kick`          | **pulse**              | Sine pitch-sweep (high→low) + noise click + soft-clip drive. The metronomic, punchy 4-on-the-floor kick. |
| `rumble`        | **sub weight**         | The kick fed through a parallel feedback-comb "reverb" network, lowpassed and distorted, front-ducked to sit under the kick. The sustained low-end mass beneath the pulse. |
| `hat`           | **subdivision / drive**| Highpassed noise blended with a stack of detuned square waves (`tone`). Closed = short/tight (16th/8th drive); open = longer decay (accent/lift). |
| `clap`          | **backbeat**           | Several short noise "flam" bursts + a bandpassed decaying tail. The snappy 2-and-4 accent. |
| `ride_or_perc`  | **texture**            | An inharmonic tone stack blended with noise, highpassed. Groove ornamentation / ticking texture. |
| `stab`          | **hook**               | Detuned unison saw/square voices → lowpass → soft-clip drive. The melodic/harmonic hook element. |
| `pad`           | **space**              | Slow additive harmonic stack with a raised-cosine attack/release, lowpassed. Ambient bed under breakdowns. |
| `riser`         | **transition (build)** | Exponential pitch sweep blended with brightening noise, quadratic rising amplitude. Builds tension into a drop. |
| `impact`        | **transition (hit)**   | Low sine boom + noise splash + long comb-reverb tail. Marks a hard transition point. |

`engine.loop(bpm, bars, tracks, sidechain)` places any of the above on a
16-step grid at a given BPM (with per-hit velocity), returns the mixed loop
and per-track stems, and can duck one stem (e.g. `rumble`) around another's
hits (e.g. `kick`) to emulate sidechain compression.

`presets.hard_techno_bar(bpm, variant)` assembles a canonical modern
hard-techno bar from these primitives: `'core'` (kick+rumble+hats+clap),
`'full'` (+stab, perc), `'drop'` (everything, denser hats, ride),
`'breakdown'` (pad+hats, no kick), `'buildup'` (4 bars: riser under a
clap roll that doubles in density each bar).

## Running the sweeps

From `/home/user/sound-function`:

```
python3 -m synth.sweeps
```

This renders one WAV per swept parameter value to `out/sweeps/<sound>__<param>__<value>.wav`,
and every preset variant (plus its stems) to `out/loops/<variant>.wav` /
`out/loops/<variant>__<track>.wav`.

## Tests

```
python3 -m pytest synth/test_engine.py
# or
python3 synth/test_engine.py
```

Checks finiteness/peak bounds, requested lengths, that a kick's settled
pitch lands within 10 Hz of `pitch_end_hz`, that a closed hat's spectral
centroid is > 5 kHz while a kick's is < 400 Hz, that rumble energy
concentrates below its lowpass cutoff, and that rendering is
seed-deterministic (identical arrays across repeated calls).
