# Lessons

Every instrument that turned out bent, how it was caught, what fixed it. Read
before touching any measure. The pattern: none were caught by review; all
were caught by contact with real material.

## decay_ms and duration_s measured pitch, not time (found 9 Sep)

`analysis/signal_features.py` scanned the raw absolute waveform for the first
sample below a threshold after the peak. A waveform passes near zero every
half cycle, so the first sub-threshold sample arrives within half a period.
A hat with a 15 ms tail and one with a 250 ms tail both read 0.113 ms. Every
sound in the library reported a decay under 4 ms, pads included.

Caught by measuring the survey stimuli against real drums. Fixed with an
analytic-signal envelope, overlap-normalised smoothing, and, for the -60 dB
duration, a slope fit from peak to -30 dB extrapolated, because the envelope
has a numerical floor near -50 dB. Two traps inside the fix: a 2 ms RMS window
is itself frequency-dependent (a 50 Hz and a 2 kHz tone with the same decay
read 66 and 116 ms), and passing the rectified signal to the Hilbert
transform gives the wrong envelope. Regression tests in
`analysis/test_features.py`. Cost to the classifier: none, the selector
already preferred the windowed `decay40_ms`. Cost to anyone reading the
numbers: total.

## The listening test played sounds that were not what they were called (9 Sep)

Synthetic stimuli: 40% of feature checks outside the p10 to p90 band of real
one-shots of the same job; attack time wrong on 38 of 58. Fixed by building
stimuli from real one-shots with one thing changed: 15%, attack 7 of 46.
`listen/realism_check.py` is the check; run it on any new stimulus set,
including a future pack rendered from Anthony's own racks.

## The pump measure saturates near 12 to 14 dB (11 Sep)

`band_pump.py`'s depth, fed an exact broadband duck: 6 -> 4.5, 12 -> 8.1,
24 -> 12.3, 40 -> 13.9 dB. Confirmed on the Mac with a real kick: 24 -> 11.8,
40 -> 13.4. Every published pump depth above about 12 dB is a floor. The
ordering across labels is probably safe; the absolute values are not. It does
NOT invent a split between bands (within 0.5 dB), so the H34 corpus verdict
stands. On a solo stem that goes near-silent between kicks the measure returns
nonsense (41 and 71 dB); a per-beat min/max variant is worse.

## Stems sized from the whole set were 57% silence (12 Sep, Mac)

`song.last_event_time` is the last event anywhere in the set. HW002's tracks
end at beat 704 of 1630. Every stem in `live_multitrack_bounce_v1` is 614 s
of which 264 s is music. Size from the source track's own clips. The tools
now find content length themselves.

## Two takes must be aligned before dividing (12 Sep, Mac)

Two real-time recordings started 251 samples apart. Unaligned division gave
wandering depths and a spurious split. A naive cross-correlation returned one
whole beat, the material's period. Constrain the lag search to under half a
beat. `duck_calibration.py bypass` does this; verified on a shifted synthetic
pair.

## Schema drift nearly produced a false finding (9 Sep)

`analysis.run hits` does not produce `decay20_ms`, `decay40_ms`,
`sustain_share`; `analysis/hits_extra.py` adds them. Re-extracting without the
second pass dropped three columns and made classifier accuracy appear to fall
from 0.346 to 0.299 after the decay fix. Always run both; diff column sets
before comparing models.

## Smaller traps

- `pgrep -f` matches its own wait-loop's command line. Anchor patterns
  (`^python3 corpus2/band_pump`) and never put the pattern in the loop's own
  text.
- A multiprocessing pool with no per-task timeout hung ten hours at 650 of
  662. Use an in-worker `SIGALRM`, resume from saved output, save
  incrementally.
- The site sync copied `ops/local.env` (the ntfy topic) into the public
  mirror. Now excluded by name; the topic was rotated. Secrets never go in a
  directory the sync walks.
- Real-time stem filenames collided with old synthetic ones
  (`clap__decay_ms__140`); new sets are namespaced by set id.
- launchd's PATH does not include `~/.local/bin`, where the native Claude Code
  installer puts `claude`. The poller found nothing and left no trace. Log
  every run; preflight the binaries.
- Plugins can hide from the Live API. LFOTool exposes only on/off and stores
  state as an opaque blob. pedalboard sees everything. The measurement
  (identical dip timing across bands) answered what the settings could not.
- LFOTool on the rumble pumps about 9 dB, not "to silence". The silence
  reading was the bypass division's own fault (envelope follower, depth
  against the curve's max, next-onset wrap-in), fixed 12 Sep. When a number
  looks impossible for the device, read the device's state before believing
  the measure.
- pedalboard has no transport: tempo-synced modulation plugins render as if
  stopped. Use DawDreamer for those. Audio Units do not load under tmux.
- A Mac that sleeps freezes Live's transport with `is_playing` still true.
  `caffeinate -dis` around every long run; power, lid, pmset.
- Hammerspoon can interfere with Live and bake dropouts into takes. Check
  take integrity (duration, dropouts) before trusting a bounce.
