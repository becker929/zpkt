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

Made on the night of 14 October 2026 in two rounds: 86 images, then 57 more for the sleeves, the title, the walk
frames and a new `ground-a` (143 in all).

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
- 28 props;
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

**Batches** (all on the wall, `/studio/images/?batch=<name>`):

- `rummage-style-1`, `rummage-style-2`;
- `rummage-props-1` (its first three, in the round-1 style, are unused), `rummage-props-2`;
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
