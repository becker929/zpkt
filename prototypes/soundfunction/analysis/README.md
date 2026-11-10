# analysis — feature extraction for hard-techno structural role

Two kinds of features, two modules, one CLI, one plotting module.

## `signal_features.py` — one isolated sound (a hit / short stem)

`describe_hit(y, sr) -> dict`, `describe_file(path) -> dict`. Plain-English meaning of each field:

- **duration_s** — time from onset to where the envelope has decayed 60 dB below its peak.
- **attack_ms** — time from onset to the sample peak. **rise_10_90_ms** — the classic 10%→90% rise time (steeper = punchier).
- **decay_ms** — time from peak down to -20 dB (the initial drop-off, before the tail).
- **t60_estimate_ms** — a reverb-style *estimate*: fit a line to the dB-envelope's decay slope (in the -5 to -35 dB range when available) and extrapolate to -60 dB. It is an estimate, not a measured RT60 — say so, don't trust it below a handful of milliseconds of usable decay.
- **rms_db / peak_db / crest_factor_db** — overall level, peak level, and how "peaky" vs "sustained" the sound is (peak − rms).
- **loudness_a_db** — an A-weighted RMS *loudness proxy* (standard IEC 61672 A-weighting analog prototype, bilinear-transformed to the file's sample rate). This is **not** a certified LUFS/LKFS meter — it is a perceptually-adjusted level proxy only.
- **spectral_centroid_hz** (whole sound) and **spectral_centroid_hz_100ms** (first 100 ms only) — "brightness"; comparing the two tells you if a sound opens bright and settles dark, or vice versa.
- **spectral_bandwidth** — spread of energy around the centroid. **spectral_rolloff_85** — frequency below which 85% of the energy sits. **spectral_flatness** — 0 (tonal) → 1 (noise-like). **spectral_flux_mean** — average frame-to-frame spectral change (from `librosa.onset.onset_strength`). **zero_crossing_rate** — a cheap extra noisiness/pitch proxy.
- **band_{sub,low,lowmid,mid,high,air}_share** — fraction of spectral energy in 20–60 / 60–150 / 150–400 / 400–2000 / 2000–6000 / 6000–16000 Hz, summing to 1 across those six bands.
- **f0_hz** — median pitch estimate (`librosa.pyin`) and **f0_voiced_confidence** — mean voiced probability. **f0_hz_at_5ms/30ms/100ms** — the pitch specifically at those times after onset, i.e. a kick's pitch *sweep* (short-attack synth kicks sweep from a few hundred Hz down to the fundamental within tens of ms).
- **harmonic_percussive_ratio** — energy(harmonic) / energy(percussive) from `librosa.effects.hpss`; high = tonal, low = noisy/transient.
- **centroid_slope_hz_per_ms** — linear-fit slope of the centroid over time: positive = brightens, negative = darkens as the sound plays out.

## `context_features.py` — a sound's *role* inside a full mix

`describe_track(path, npy_path=None) -> dict`. No stems needed — everything is read off the full mix using the same six frequency bands as above, each with its own per-band onset-strength (spectral flux) envelope.

- **tempo_bpm_raw / tempo_bpm / tempo_correction** — `librosa.beat.beat_track`'s raw estimate, plus a sanity check against doubled/halved octave errors (kept if it lands in the ~130–190 BPM techno range). Beat tracking itself runs on a **kick-weighted (sub+low) onset envelope**, not the full-mix envelope — in hard techno the kick is a far more reliable pulse than hi-hats/percussion, and locking onto the raw mix envelope was empirically found to grab the wrong 16th-note phase on test material.
- **bands.<name>.bar_profile_16step** — a 16-bin histogram (folded onto the bar's beat-derived 16th-note grid) of where that band's onsets land. **top_bins** — its busiest 3 grid positions. **syncopation_score** — energy on the 12 non-beat 16ths ÷ energy on the 4 quarter-note beats (bins 0/4/8/12).
- **bands.<name>.onsets_per_bar / density_0_1** — how often the band fires. **periodicity_strength** — normalised autocorrelation of the band's flux at 1 beat / 2 beats / 1 bar lag (near 1.0 = very repetitive at that period).
- **kick.kicks_per_bar / kick_beat_fraction / kick_fraction_per_bar** — sub+low onsets quantised onto the quarter-note beat grid: `kick_beat_fraction` is the overall fraction of beats carrying a kick (~1.0 in a drop, ~0 in a breakdown); `kick_fraction_per_bar` is that same fraction per individual bar.
- **segments / candidate_breakdown / candidate_drop_bar** — a bar-resolution novelty curve (bar-to-bar distance between z-scored [per-band energy, 6-coefficient MFCC, kick fraction] vectors, peak-picked with `scipy.signal.find_peaks`) gives segment boundaries; each segment is labelled `kick-on`/`kick-off` from its mean kick fraction. The longest `kick-off` run is the candidate breakdown; the first `kick-on` bar after it is the candidate drop. *(This is a simplified single first-order novelty curve, not a full checkerboard-kernel self-similarity-matrix — chosen for robustness on short loops; it can miss soft/gradual transitions.)*
- **entry_exit.<band>** — per segment, whether that band's mean energy is active (>15% of its track-wide max) — e.g. "present in drops, absent in breakdowns".
- **bar_matrix / bar_matrix_bands_order / bar_matrix_npy** — the raw bands × bars energy matrix, returned inline (JSON-safe nested list) and, when `npy_path` is given (or always, via the CLI), also saved as a `.npy` file for plotting.

## `run.py` — CLI

```
python3 -m analysis.run hits   corpus/hits/  -o out/hits.csv
python3 -m analysis.run tracks corpus/tracks/ -o out/tracks.json
```

Accepts directories (searched recursively) or individual files, in wav/mp3/ogg/flac (via librosa + ffmpeg). One bad file never aborts the run — it's logged to stderr and skipped; progress is printed to stderr per file. `hits` also parses `<sound>__<param>__<value>.wav`-style filenames into `sound`/`param`/`value` CSV columns (blank if the name doesn't match). `tracks` also writes `out/<trackstem>.bars.npy` per track.

## `plots.py`

Needs `matplotlib` (`pip install matplotlib` if missing — no other new dependency). Dark, restrained style (near-black background, one accent colour per band, minimal chrome) meant for embedding on a dark web page. Saves both PNG and SVG.

- `plot_sweep(csv, sound, param, features, out_dir=...)` — one line plot per feature vs the swept value.
- `plot_bar_profile(track_json_entry, out_dir=...)` — 6-band × 16-step heatmap of where each band hits in the bar.
- `plot_track_bands(bars_npy, boundaries=..., breakdown=..., drop_bar=..., name=..., out_dir=...)` — normalised per-band energy across bars, with segment boundaries, the breakdown shaded, and the drop bar marked.

## Tests

```
python3 analysis/test_features.py
```

Runs against synthetic fixtures generated on the fly (`fixtures.py`: a sine burst, a noise burst, a clicked descending sine sweep, and a 16-bar 150 BPM click-track with a kick-like thump on every beat except bars 9–12, and a noise tick on every offbeat 8th throughout) — no real corpus or synth output required. All checks currently pass.

## Known limitations (said plainly, not glossed over)

- **t60_estimate_ms** is a coarse slope-extrapolation, not a real RT60 measurement; on very short or non-monotonic decays it can be noisy or `nan`.
- **Section-boundary detection** uses a first-order (bar-to-bar) novelty curve rather than a full checkerboard-kernel self-similarity matrix; it is robust on clearly-gated kick-on/kick-off material (the intended breakdown/drop use case) but will under-segment tracks with gradual, non-percussive transitions.
- **Beat tracking** is deliberately kick-weighted for this genre; on tracks with a very weak or absent kick it will fall back to whatever low-band energy exists and may mistrack.
- **f0 / pyin** on very short or noise-dominated sounds can return an all-`nan`/unvoiced track — `f0_voiced_confidence` should always be checked alongside `f0_hz`, not the other way round.
- **loudness_a_db** is explicitly a proxy (A-weighted RMS), not a calibrated loudness standard (no certified LUFS meter is available in this dependency set).
