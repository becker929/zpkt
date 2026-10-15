# The map checklist's check sounds

Six check sounds for `/studio/checklist/map/`, made in Ableton Live and played by the page as rendered
(`docs/sound.md`). Each is three layers, all stock Live devices and no samples:

- **Body**: Operator, a sine with a fast pitch drop and some feedback, through a Saturator. Pitched 98-147 Hz so
  its harmonics carry on a phone speaker.
- **Click**: Operator, white noise for a few milliseconds, high-passed. The transient.
- **Splash**: Operator, a sine frequency-modulated by noise (or by a sine at 7x for the metallic one), filtered,
  with an Echo (ping-pong). The splashy mid-high.

The click and the splash also feed a ping-pong Delay return. Main has Drum Buss (distortion, crunch, transients,
boom), Glue Compressor and a Limiter (ceiling -3.5 dB, the headroom AAC needs). The variants differ in those
settings (`variants.py`): Anvil, Vault, Crack, Slam, Block and Thunder. Each renders three times: the hit; a
heavier one for a commit that finishes a step (longer body and splash, more feedback and boom); and a soft knock
for the box settling back into its row (body and click, 12 dB down).

```bash
cd hands
# in Live: File > New Live Set (Live's default: two MIDI, two audio, Reverb and Delay returns), then
uv run python scripts/ui_sounds/make.py build
uv run python scripts/ui_sounds/make.py render anvil          # hit, strong and land: three exports, ~40 s each
uv run python scripts/ui_sounds/make.py measure
uv run python scripts/ui_sounds/make.py encode               # -> <data_dir>/ui_sounds/web/*.m4a + map/sounds.json
uv run python scripts/ui_sounds/make.py upload               # -> R2, audio/zpkt/check-sounds/ (wrangler's login)
```

Audio never goes in git. The files are named by their content and kept in R2; `sounds.json` (in the repo) names
them, and the harness's `check_sound` route copies each from the site once (the site's audio has no CORS headers
for the harness's origin) and serves it from that copy.

Notes from making them (14 October 2026):

- Use the Live 11+ note calls (`remove_notes_extended`, `add_new_notes`). The legacy `set_notes` and
  `remove_notes` raise a prompt about "an older process to modify MIDI notes", which blocks the LOM until
  someone answers it.
- Keep renders out of `~/Music`. A Save panel there made macOS ask for Live's access to the Apple Music library.
- Operator's Volume is not linear: 0.4 is about -18 dB. The first splash was inaudible under the body for that
  reason.
- Raw energy shares mislead here. The splash can be 1 % of the energy and still half of what is heard, since the
  ear (and a phone speaker) weights 2-5 kHz far above 100 Hz. Judge by ear; the measurements only catch clipping,
  late onsets, cut tails and levels.
