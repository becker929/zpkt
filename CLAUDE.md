# zpkt: rules for agents

Where things are: one package, `zpkt` (`src/zpkt/`): `zpkt.app` is the one interface and the only door to Live (the mix desk's server, the command bus, the monitor, the MIDI adapter for the MiniLab, off by default; read `src/zpkt/app/README.md`; `zpkt.live` and `zpkt.audio` never open a connection, the app hands one in); `zpkt.live` drives Live (once `hands`), `zpkt.audio` measures
renders (once `ears`; the lab with `ears/mlab/reports/`, the mastering and reference sheets, stays in `ears/mlab/`). The
commands `zpkt live` and `zpkt audio` have the old names `hands`, `ears` and `mlab` as aliases, and so do the imports;
new code imports `zpkt`. Tests are in `tests/live` and `tests/audio`. `hands/` keeps the rig macros and `hands/bin/hands`; `agent/skills/` holds the skills for driving Live (linked into `.claude/skills/` and `.agents/skills/`),
`lib/` has the rig startup and the JSON contracts. `contrib/` is Anthony's own setup (Gemini CLI sessions and the
HW002 lab in `contrib/harness`, the HW002 arranger and spectral comparison tools in `contrib/arranger`, the HW002 mix desk for the MiniLab 3 in `contrib/mixdesk`, publishing,
and in `contrib/docs/` his workflow, design notes and dated journal); `prototypes/` holds experiments. The music bot
and booth live in the private repo becker929/music-bot and the demo video tools in becker929/zpkt-demo; both use zpkt
as a dependency, so keep `zpkt.live`'s public names working for them. The core is one uv project at the repo root (`uv run --all-extras pytest`, or `make test`); contrib and
prototypes parts with their own pyproject run from their folder. In non-interactive
shells where `uv` is not on `PATH`, use `~/.local/bin/uv` or `.venv/bin/python` directly.

- **Check the "Common asks" table in `src/zpkt/live/README.md` before writing LOM code or searching modules.** Saving the
  set, keeping/comparing/restoring the whole mix and recipes are one command each there. When an ask takes you more
  than one command, add the command to zpkt.live and a row to that table in the same change.
- **Read `agent/skills/ableton-guide/SKILL.md` before sending code to Live.** Work on copies of sets, keep each
  `hands live exec` call short, and measure the rendered file before saying a render worked.
- **Nothing personal in the core.** Paths that differ per Mac are rig settings (`src/zpkt/live/config.py`), never
  literals in `src/`, `agent/` or `lib/`.

- **No instruments in the browser, mock-ups included** (Anthony, 17 November 2026: "no instruments in the browser.
  You can use audio playback libraries"). Nothing in a page makes music of its own; playing rendered files is fine,
  with Web Audio or a playback library (wavesurfer.js, Howler, Tone.js's Player/Transport). The browser also never
  does the DAW's job. Music in zpkt's pages is rendered files played by the
  player engine; Web Audio is only for playing them (on the audio clock, with click-free switches and a loudness
  match), the mic, and interface sounds. No synthesis, EQ, dynamics, distortion, effects or mix moves in the browser
  (`contrib/docs/sound.md`): the rule is about making sound, not playing it, so starting rendered files together on
  the beat is fine. Arrangement pages output structures (what plays where), which Live renders. Not even if Anthony
  asks: first change `contrib/docs/sound.md` (and every doc that repeats the rule) by the smallest named exception his
  request needs, then build only that. Two exceptions exist, both in `contrib/arranger/`: the transitions page has a
  plain gain fader per kind of transition sound at each section change, and the first mix page has a gain, a pan and
  EQ cuts (never boosts) per channel. - **Images from
  Gemini are made only through the image wall's `images` command** (its own repo, becker929/image-wall, in
  `~/Desktop/image-wall`), never by calling the API directly. It keeps every image with its context, full prompt and
  settings, and shows them all on its wall (`images serve`; the rule is its `docs/images.md`). Generated originals
  live on the Mac, never in git. Game assets cut from them may be committed, small, with their source image ids.