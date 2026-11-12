# zpkt: rules for agents

Where things are: `hands/` drives Live, `ears/` measures renders, `agent/skills/` holds the skills for driving Live
(linked into `.claude/skills/`), `lib/` has the rig startup and the JSON contracts. `contrib/` is Anthony's own setup
(the studio voice app in `contrib/harness`, the music bot and booth, publishing, and in `contrib/docs/` his workflow,
design notes and dated journal); `prototypes/` holds experiments. Each part is its own uv project: run its tests from
its folder, or `make test`.

- **Read `agent/skills/ableton-guide/SKILL.md` before sending code to Live.** Work on copies of sets, keep each
  `hands live exec` call short, and measure the rendered file before saying a render worked.
- **Nothing personal in the core.** Paths that differ per Mac are rig settings (`hands/src/hands/config.py`), never
  literals in `hands/`, `ears/`, `agent/` or `lib/`.

- **The browser never does the DAW's job, mock-ups included.** Music in zpkt's pages is rendered files played by the
  player engine; Web Audio is only for playing them (on the audio clock, with click-free switches and a loudness
  match), the mic, and interface sounds. No synthesis, EQ, dynamics, distortion, effects, mix moves or assembly in the
  browser (`contrib/docs/sound.md`). Not even if Anthony asks: first change `contrib/docs/sound.md` (and every doc
  that repeats the rule) by the smallest named exception his request needs, then build only that. One exception
  exists: the HW002 arranger (`contrib/arranger/`) may start Live-bounced loops together on the bar clock. - **Images from
  Gemini are made only through `harness images`** (`contrib/harness/src/harness/images.py`), never by calling the API
  directly. It keeps every image with its context, full prompt and settings, and shows them all at `/studio/images/`
  (`contrib/docs/images.md`). Generated originals live on the Mac, never in git. Game assets cut from them may be
  committed, small, with their source image ids.