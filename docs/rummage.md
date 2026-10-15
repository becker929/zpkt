# The Rummage: a region you play to finish a short (SH001)

Anthony, 14 October 2026, before an overnight run: "pause HW002. I want you to create a fresh track which corresponds
to a permanent region in the world with permanent artifacts ... an art style that is collage, bric-a-brac, faux
multi-material. Do iterations of art, music, software performance, testing, and iterate that loop ... I expect to
wake up to a new region where I can actually complete a new short by playing it."

This is the brief the overnight agents share. HW002 is paused.

## The loop the player plays

1. **Walk in.** The Rummage is a region of its own: a junk-market wasteland of cut-out bric-a-brac on layered
   paper, cork, fabric and tin. You enter through a tear in the storm from the 1-bit Wasteland
   (`/studio/checklist/wasteland/`), or straight at `/studio/checklist/rummage/`.
2. **Find the three machines.** Each is a giant synthesizer module made of bric-a-brac, standing like a megalith:
   - **The Wireless**: the bed (collage step);
   - **The Clatter**: the drums;
   - **The Bellows**: the low end (bass).
3. **Operate a machine.** Walk up to it and tap Operate. The machine fills the screen: its panel art, a big
   three-way selector, a play/stop control and a commit lever. The short plays with this machine's option swapped
   in, switched on the audio clock with no click and loudness-matched. The other parts are what you committed, or
   option 1 where you haven't committed yet.
4. **Commit.** Pull the lever. The choice is distilled into an **artifact**, a small collage object with juice (it
   is stamped and shaken, and falls into your hands). You carry it (it shows on the wanderer). You can carry one at
   a time.
5. **Carry it home.** Bring it to **The Gramophone**, the track's machine at the heart of the region, and put it on
   its plinth. The Gramophone shows three slots, one per machine: it is the track's checklist as a machine.
6. **Finish the short.** When all three slots are filled, the Gramophone plays the short as made: the
   pre-rendered combination of your three choices. A plate is hung in the museum (the artist's gallery, track
   `sh001`), and the region keeps your artifacts on the Gramophone for good. You can recommit a machine later. A
   new artifact replaces the old one on the plinth, and the short updates.

Nothing is locked, in the spirit of the spine (`docs/studio-agent.md`): any machine can be operated in any order.

## Music (SH001)

- **Made in Ableton Live** (Live 12 Suite on this Mac) by hands, played as rendered (`docs/sound.md`, `CLAUDE.md`).
  The browser only plays the renders, with click-free switches and a loudness match.
- **A short:** 32 bars at the tempo the music agent picks (about 60 s). Fixed arrangement:
  - bars 1-8: bed;
  - bars 9-16: + drums;
  - bars 17-28: + bass, full;
  - bars 29-32: an outro / tail.
- **Three parts with three options each:**
  - `bed` 1-3 (textural and harmonic beds, collage and found-sound in feel);
  - `drums` 1-3 (junk percussion, clank, tin);
  - `bass` 1-3.

  Each option has a short name and a one-line description the page shows.
- **27 renders:** every combination, `sh001-<bed>-<drums>-<bass>`, all the same length and tempo, so switching
  keeps the playhead. Each is measured (integrated LUFS) and gets a `gain_db` for the loudness match. They're
  encoded AAC .m4a.
- **Where:**
  - renders on the Mac only, under `~/_agent_scratch/studio/regions/rummage/audio/` (never in git, never
    `~/Music`), served by the harness at `/studio/regions/rummage/audio/<file>`;
  - the manifest, `static/checklist/rummage/audio.json`, is in git (no audio);
  - the recipe, `hands/scripts/rummage/` (build | render | measure | encode, like `hands/scripts/ui_sounds/`), is in
    git.
- **Sounds:** Live's own instruments, devices and packs only (look for the Lost and Found pack: instruments made from
  found objects). No purchased reference audio and nothing from Anthony's library.
- **Live discipline** (`hands`):
  - one checked step at a time;
  - `hands live modals` / `hands live check` before each step;
  - short LOM calls;
  - the Live 11+ note API only (`add_new_notes`, `remove_notes_extended`);
  - render outside `~/Music`;
  - screenshots (`screencapture -x -D 1`) to read dialogs.

  Tonight Anthony allowed aggressive recovery: kill and relaunch Live, clear Live's dialogs. macOS security
  (TCC) prompts are never clicked.

`audio.json`:

```json
{ "track": "sh001", "bpm": 120, "bars": 32, "seconds": 64.0, "sample_rate": 44100,
  "parts": { "bed": [{ "id": 1, "name": "Music box & hiss", "about": "..." }, ...], "drums": [...], "bass": [...] },
  "combos": { "1-1-1": { "file": "sh001-1-1-1-<hash8>.m4a", "lufs": -13.8, "gain_db": -0.6 }, ... } }
```

## Music (as made)

The music agent's account of SH001 as rendered (15 October 2026). The recipe is `hands/scripts/rummage/` (README,
`parts.py` for the music, `make.py` for the steps, `liveops.py` for Live).

- **118 BPM, 4/4, 32 bars = 65.085 s, D minor with a dorian colour.** Two bars a chord: Dm9, G9, Bbmaj7, A7sus4 to
  A7, three times; the last time round turns home: Dm9, G9, Bbmaj7, D(add9). One tune over the eight-bar cycle (A, A,
  a higher answering phrase over the full groove, then A turning home), the same in every bed, so any bed sits with
  any drums and any bass.
- **Arrangement:** bars 1-8 the bed alone (it swells in over the first four bars); 9-12 kick and hats; 13-16 the whole
  kit, a fill at 16; 17-28 the bass and the full groove (extra percussion, fills at 24 and 28); 29-32 the outro: one
  last hit, the bass holds Bb then D, the bed rings out on D(add9). A shared track of found sounds marks the seams in
  every combo: a cassette going in at the start, a radio tuning in over bars 7-8, a noise riser and a broken box into
  bar 17, a dropped thing and vinyl run-out crackle at 29.
- **The options** (all Live 12 Suite Core Library; the Lost and Found pack is not installed on this Mac):

| Part | Option | What it is |
|---|---|---|
| bed 1 | Music box & hiss | Music Box picks out the tune over its own eighth-note arpeggio, through Chorus-Ensemble, over a looping tape-noise sample |
| bed 2 | Parlour upright | Childhood Home Piano in a lopsided, syncopated comp; Toy Piano Bells on the tune an octave up, detuned by a chorus |
| bed 3 | Branches & tin bowl | Tree Branches (a pad of rustling branches) holds the chords; Tin Bowl sings the tune at half speed |
| drums 1 | Tin-can break | Rattle Kit: a broken beat of slaps, a wooden box, buzzing tin, a cracked cowbell |
| drums 2 | Clockwork four | Clockwork Kit: four on the floor, a clanking off-beat, a ticking clock |
| drums 3 | Cutlery shuffle | Perc Kitchen Kit (spoons, knives, pans, glass) in triplets over a Kick Wood sample |
| bass 1 | Round sub | Sub Mellow through Saturator's Bass Shaper, long notes on the roots |
| bass 2 | Rubber band | Tension Rubber Bass, plucked and skipping around the beat |
| bass 3 | Bowed gut | Cat Gut Bass, roughened by a hard-curve Saturator, gliding through the changes |

- **Mix:** each option balanced alone through Main (its own render, measured: options within about 1.5 LU of each
  other), then Main: EQ Eight high-pass at 32 Hz, Glue Compressor (2:1 at -12 dB, 10 ms, auto release), Limiter
  (True Peak, ceiling -1.8 dB). The 27 renders land at -14.5 to -14.1 LUFS integrated, true peaks -1.4 dBTP or lower;
  `gain_db` (+0.1 to +0.5) brings each to -14.
- **Rendering:** every combo is the same set with only the nine option tracks' mutes changed, exported through Live's
  own Export dialog: 32 bars, 24-bit WAV, about 18 s each, the 27 in 8.5 minutes; all 27 are 2,870,238 samples. Each
  WAV is checked (length to 10 ms, not silent), measured with ffmpeg's EBU R128 meter and encoded with Apple's AAC
  encoder at 192 kb/s; each .m4a is checked again (length, loudness within 0.3 LU of its WAV) before any is added.
  New renders are added beside the old ones in the audio folder (the names carry a content hash) and never replace a
  file an audio.json names.
- **Rounds:** v1 (commit 3207db2) the first 27; v2 the seams track, humanizing, the beds' swell, a rebalance (the
  27 within 0.5 LU before the match); v3 the answering phrase in bars 17-24; v4 bed 1's tape hiss raised 19 dB (at
  -61 dBFS it was inaudible; now about 20 dB under the music box), the nine bed-1 combos re-rendered; v5 the ending
  (the last notes let go in time for their tails to die inside bar 32: bed 3 had ended at -21 dBFS on the last
  sample, now -67; the hiss and the run-out crackle fade out) and the bowed bass passing Bb-G-A. Probing and
  listening stand-ins: spectrograms, band shares and per-bar chroma against the chords (the beds put 83-93 % of their
  pitched energy on chord tones), since the agent cannot hear the renders.
- **Gotchas:** two macOS permission prompts sat over Live all night and took every keystroke, so hands' export
  script could not type; `liveops.py` exports and saves through the menu bar and accessibility only (see its
  docstring). Live keeps one note per pitch and start (duplicates are dropped before writing). Selecting Main by LOM
  can silently fail right after a view change, and a device load then lands on another track (the selection is now
  read back). The LOM cannot write automation into arrangement clips, so the beds' swell is in their velocities.

## Art

- **Style:** collage, bric-a-brac, faux multi-material. Cut-outs with a thin white paper edge, mixed textures (wood
  grain, brass, enamel, kraft paper, fabric, tin, print), a hand-made, stop-motion feel. The wanderer keeps the gold
  scarf.
- **Made with Gemini through `harness images` only** (`docs/images.md`): every image with its context and batch,
  batches named `rummage-*`.
- **Processing:** generated on a flat chroma background, keyed out, trimmed, resized (sprites at about 2x their
  largest on-screen size), and written as WebP with alpha into `static/checklist/rummage/art/`. Committed, small.
- **`art/manifest.json`** names every asset with its source image id:

```json
{ "version": 1,
  "ground": [{ "id": "ground-a", "file": "ground-a.webp", "w": 1024, "h": 1024, "src": "<image id>" }],
  "path": { "file": "path.webp", "w": 512, "h": 256, "src": "..." },
  "props": [{ "id": "teapot", "file": "props/teapot.webp", "w": 240, "h": 260, "anchor": [0.5, 0.94], "foot": 0.32, "src": "..." }],
  "machines": { "bed": { "file": "machines/bed.webp", "w": 360, "h": 620, "anchor": [0.5, 0.96], "foot": 0.4,
                         "panel": "panels/bed.webp", "src": "...", "panel_src": "..." },
                "drums": { ... }, "bass": { ... } },
  "gramophone": { "file": "gramophone.webp", "w": 600, "h": 640, "anchor": [0.5, 0.95], "foot": 0.42, "slots": [[0.25, 0.8], [0.5, 0.85], [0.75, 0.8]], "src": "..." },
  "artifacts": { "bed-1": { "file": "artifacts/bed-1.webp", "w": 160, "h": 160, "src": "..." }, ... },
  "hero": { "front": { "file": "hero/front.webp", "w": 140, "h": 220 }, "back": { ... }, "side": { ... } },
  "portal": { "file": "portal.webp", "w": 300, "h": 360, "anchor": [0.5, 0.95], "src": "..." } }
```

- `w`/`h` are the file's pixels. The page draws sprites at half that in world units, which is CSS px at zoom 1.
- `anchor` is the base point as fractions of the sprite.
- `foot` is the collision radius as a fraction of the sprite's width.

### Art (as made)

Made on the night of 14 October 2026, in three rounds (164 images in all):

1. 86 images: the style and the region's assets;
2. 57 more: the sleeves, the title, the walk frames and a new `ground-a`;
3. 21 more: set pieces, rugs, edge walls and 4 props, to give the market shape.

**The style.** Engraving-led cut-out collage, after two style rounds:

- the first round tried seven takes on the brief (photo collage, Gilliam engraving cut-outs, Höch photomontage, a felt
  and tin diorama, scrapbook ephemera, a Cornell box, bold mixed-material cut-outs);
- the two that read best as game art were blended in the second round, and the engraving-led blend won:
  - a drawn ink line holds 46 separately generated sprites together, which photographic cut-outs didn't;
  - the outline and the white paper edge keep the silhouettes readable at phone size;
  - the photographed material inlays (brass, enamel, gingham, tin) keep it faux multi-material;
- the style reference is `20261015-061212-398cc8` (batch `rummage-style-2`). Every asset was made with it as
  `--input`.

**The style bible** (the prompt prefix for every new asset):

> Collage art for a 2D adventure game: a hand-tinted Victorian engraving cut-out with fine cross-hatched ink
> linework, as in Terry Gilliam's cut-out animation, with inlays cut from photographs of real materials (polished
> brass, chipped enamel, gingham and tweed fabric, wood grain, rusty tin, kraft paper) on its knobs, grilles and
> panels; a big, simple, readable silhouette cut out with scissors, with a crisp thin white paper edge all around.
> Warm muted palette, soft daylight from the upper left; witty, hand-made, slightly askew, stop-motion feel. Match
> the style, linework, materials, colours and light of the reference image, but draw only the one thing described.

Sprites add: "The object: ... Seen from a top-down three-quarter view (camera high above, looking down at about 45
degrees), as in a 2D adventure game. Exactly one object, whole and uncropped, centred, filling about 80% of the
frame height, on a perfectly flat, uniform pure magenta (#FF00FF) background. Nothing else in the frame: no ground,
no cast shadow, no floor, no other objects, no text, no letters, no numbers, no border." Never say "phone" or
"mobile game" in a scene prompt: it comes back as a picture of a phone.

**Colour code.** Each part has an accent, on its machine, its panel, its artifacts and its plinth:

- `bed`: amber and teal;
- `drums`: tomato red and tin;
- `bass`: deep blue and brass.

**What is in `art/`:**

- 3 tiling grounds:
  - `ground-b` (cork and felt patches) is the calmest base;
  - `ground-a` (small, even scraps of kraft and ledger paper) is a variant;
  - `ground-c` (faded sheet music and maps) is busy, for small patches only;
- the torn-paper path strip;
- 32 props;
- 9 set pieces (`sets`, 520-780 px tall), each a composed cluster that gives the market shape:
  - a striped market stall;
  - a heap of junk;
  - a tower of suitcases and hatboxes;
  - a carousel horse;
  - a bookshelf spilling books;
  - a dresser with a mirror and lamps;
  - a tin-can pyramid with a ladder;
  - a pram full of cassettes;
  - a papered-over phone box (its sign says TELEPHONE);
- 4 rugs (`rugs`, 600 px wide, flat, for the ground layer): oriental, braided rag, patchwork quilt, a blank doormat;
- 4 edge walls (`edge`, 1200 px wide, with ragged ends so they overlap) for the border: crates, furniture,
  bedframes, pipes;
- 3 machines and their 3 panels;
- the Gramophone;
- 9 artifacts;
- 3 hero views from one turnaround sheet (`side` faces right; mirror it for left), each with 2 walk frames
  (`hero.<view>.walk`): each frame is the standing view edited to a step, and was kept only because it matches it;
- the portal;
- the title, THE RUMMAGE in ransom-note letters (`title`, 900×200);
- 27 record sleeves (`sleeves`, `<bed>-<drums>-<bass>`, 720×720), the art awarded for finishing the short.

**The sleeves** are one series:

- each is made from the style reference and the originals of its three artifacts (`--input`);
- each is one collage around the SH001 record, with "SH001" in ransom-note letters;
- each sleeve's look is set by its three choices:
  - the bed sets the ground: amber kraft and a glow (1), teal gingham and a dial scale (2), sheet music and
    wallpaper (3);
  - the drums set what holds it down: striped tin strips (1), crossed ribbon bands (2), masking tape and twine (3);
  - the bass sets the record's label: blue paper (1), studded leather (2), velvet (3);
- duds were made again:
  - artifacts missing or doubled;
  - "TICKET" in place of a letter;
  - a photo of a sleeve on white;
- tiny printed words on some letter tiles ("TICKET", "BUS") were kept as ransom-note texture.

**Conventions:**

- Gramophone `slots`: the centre of each plinth's brass dish, where an artifact's base rests, left to right `bed`,
  `drums`, `bass` (the plinths' dishes are amber, red and blue).
- Panels: the lower quarter to third is calm and dark for the selector and lever.
- `block`, on the wide set pieces (stall, heap, bookshelf) and the edge walls: a rectangular base `[w_frac, h_frac]`,
  as fractions of the sprite.
  - It is centred on the anchor and rises from it.
  - Its width is the solid part of the sprite's lower band.
  - Its depth is set by hand: 0.2-0.25 for the sets, 0.35 for the walls.
- An edge wall's anchor is the middle of its base (x 0.5): its lowest point is off-centre.

**Batches** (all on the wall, `/studio/images/?batch=<name>`):

- `rummage-style-1`, `rummage-style-2`;
- `rummage-props-1` (its first three, in the round-1 style, are unused), `rummage-props-2`, `rummage-props-3`;
- `rummage-sets-1`, `rummage-rugs-1`, `rummage-edge-1`;
- `rummage-machines-1` (unused), `rummage-machines-2`;
- `rummage-panels-1`, `rummage-panels-2`;
- `rummage-gramophone-1` (unused), `rummage-gramophone-2`;
- `rummage-artifacts-1`, `rummage-artifacts-2`;
- `rummage-hero-1` (its front view was the reference for the turnaround), `rummage-hero-2` (the turnaround sheet);
- `rummage-hero-3` (walk frames);
- `rummage-portal-1`;
- `rummage-ground-1`, `rummage-ground-2` (the new `ground-a`);
- `rummage-sleeves-1`, `rummage-sleeves-2` (remakes);
- `rummage-title-1`.

The Gemini key allows 20 requests a minute per model. Run big batches at `--parallel 4` or so, or a pause between
batches.

**To remake or change an asset:**

1. Make the image with `harness images` (the style bible, `--input` the style reference, magenta for sprites).
2. Put its id in `lib/harness/scripts/rummage-art.json`.
3. Run it from `lib/harness`:

   ```
   uv run python scripts/cutout.py scripts/rummage-art.json [--only props/teapot,hero] [--sheet ~/sheet.png]
   ```

`cutout.py` does the processing:

- keys out the magenta: soft alpha only next to the background, so an object's own colours survive, and magenta in
  shadow counts as background;
- unmixes and despills the pink fringe;
- drops specks, trims, resizes premultiplied, and writes WebP under 300 KB;
- wraps the grounds along minimum-error cuts, so they tile without ghosting;
- computes `anchor` and `foot`, maps the Gramophone's slots, and writes `manifest.json`;
- cover-crops the panels and the sleeves;
- with `--sheet`, draws every asset at its on-screen size on mid-grey to review;
- with `--sleeve-sheet`, lays out the 27 sleeves in a grid.

## Software

- **The page** is `static/checklist/rummage/`:
  - `index.html`;
  - `rummage.css`;
  - `main.js`: the loop, the input (a floating stick, tap-to-walk, the keys, as in the Wasteland), and the camera
    (SmoothDamp with an eased look-ahead, as in the Wasteland);
  - `scene.js`: the collage renderer at device resolution, with ground layers, props sorted by y, soft drop
    shadows, slight rotations and a stop-motion "boil" (each sprite steps between two or three tiny offsets at
    about 8 fps);
  - `hero.js`: the cut-out wanderer, with a hop and a tilt for a walk, and the carried artifact on his back;
  - `region.js`: the layout, deterministic from a seed: the Gramophone, the three machines, a scatter of props,
    torn-paper paths and the portal;
  - `flow.js`: carrying, the plinths, completion, and state through the API;
  - `art.js`: the art pack read into drawable assets (world sizes, anchors, feet), placeholders until each file is
    in;
  - `paper.js`: the materials and the placeholder art, all drawn by code (cut paper with a white edge);
  - `gram.js`: the Gramophone opened, a sheet with its three plinths and the play control, and the record sleeve
    revealed when the short is finished;
  - `stub.js`: a stand-in machine, used when `machine.js` won't load (or with `?stub`);
  - `machine.js`: the full-screen studio machine;
  - `player.js`: the short's renders through Web Audio: decoded, all started on one clock, switched with a short
    equal-power crossfade at the same playhead, `gain_db` applied.
- **Placeholders:** the page works with placeholder shapes when `art/manifest.json` or `audio.json` is missing, so
  software and art can land in either order.
- **Server** (`studio/routes.py`, `studio/regions.py`):
  - `GET /studio/api/regions/<id>/state` and `POST .../state`: the region's permanent state (committed choice per
    machine, the artifact carried, the artifacts on the plinths, completions with times), kept in
    `<studio_dir>/regions/<id>.json`;
  - `GET /studio/regions/<id>/audio/<file>`: the renders, cached forever (names carry a hash);
  - on completion, the page posts a plate to `/studio/api/artist/plates` (track `sh001`) with the render's path.
- **Thumbs:** the artist's thumbs on every view (`../map/feedback.js`), with view names `rummage`,
  `rummage-machine` and `rummage-gramophone`.
- **Tests:** `tests/ui/test_rummage.py` plays the short through, headless at iPhone size: operate, commit, carry,
  place, three times, then the short plays and the state survives a reload.
- **Performance:** about 60 fps on an iPhone. Sprites are pre-scaled to their drawn size on load, and nothing is
  decoded per frame. Measure with rAF intervals in headless WebKit at 3x.
