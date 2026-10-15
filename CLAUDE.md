# zpkt: rules for agents

- **The browser never does the DAW's job, mock-ups included.** Music in zpkt's pages is rendered files played by the
  player engine; Web Audio is only for playing them (on the audio clock, with click-free switches and a loudness
  match), the mic, and interface sounds. No synthesis, EQ, dynamics, distortion, effects, mix moves or assembly in
  the browser (`docs/sound.md`). Not even if Anthony asks: first change `docs/sound.md` (and every doc that repeats
  the rule) by the smallest named exception his request needs, then build only that.
- **Images from Gemini are made only through `harness images`** (`lib/harness/src/harness/images.py`), never by
  calling the API directly. It keeps every image with its context, full prompt and settings, and shows them all at
  `/studio/images/` (`docs/images.md`). Generated originals live on the Mac, never in git. Game assets cut from
  them may be committed, small, with their source image ids.
