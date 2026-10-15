# The Wasteland as a world to walk (design and releases)

Anthony's direction, 14 October 2026: there are two spatial systems, the gallery (a menu more than a space) and The
Wasteland (a map). Make one world, walked as a 2D character:

- **The overworld** is walked. **The map** is a separate screen that shows the points of interest.
- **Points of interest are unlocked by work**, and each unlocks a **machine** that stands for the thing unlocked
  (from his library and from the agents' work).
- **Walk to a machine and operate it**: it opens a full-screen **studio machine**. Play with the thing there, then
  **commit** settings, which are distilled into an **artifact**.
- **Carry the artifact back** to the machine that stands for the track. The checklist becomes that machine, with
  several screens.
- **The artifacts are the works of art** of `docs/artist-agent.md`. **The museum** is a place in the world to walk
  through, where they hang.

Built in small releases, each shown to him before the next.

## Releases

1. **Walk** (`/studio/checklist/wasteland/`). A hooded wanderer with a gold scarf, steered by a floating stick
   (drag anywhere; further is faster), a tap (walk to the spot) or the keyboard. The world is 1-bit, drawn by code
   from a fixed seed, so it is the same place every visit:
   - the camp in the middle, with the track's machine (HW002), a fire and a tent;
   - the museum to the south;
   - the seven sites of the spine on a ring, joined to the camp by worn paths: the scrapyard (collage), the drum
     circle, the rail yard (arrange), the drop hammer (kick), the tanks (mix), the mast (master), the gate (release);
   - between them, sand, dunes, cracked ground, rocks, dead trees, ruins, wrecks and a line of pylons, with the
     storm as the wall round the edge.

   Places name themselves as he comes near. Footprints, dust, the wind's motes, firelight and a scarf that streams
   behind are the first juice. Where he stood is kept in the browser, and the artist's thumbs are on the edges.
2. **The world, iterated.** Anthony's notes on release 1: "It jitters by a drawn pixel width constantly while
   moving"; he wants a camera with inertia and easing, a new art style made with image generation (keeping the
   trees), and machines like obelisks: "a VST or eurorack module expanded to the size of Stonehenge".
   - **The camera** is now a critically damped spring (Unity's SmoothDamp, 0.32 s) after a look-ahead that eases
     on its own (0.7 s). The look-ahead also makes up the spring's lag (velocity x smoothing time), so it really
     leads.
   - **The world is drawn straight to the screen**, an art pixel to S device pixels. It is shifted by the camera's
     remainder in device pixels, and the wanderer is placed to the device pixel. The jitter came from rounding him
     and the camera to whole art pixels separately. Measured on a steady walk, his screen position now never
     reverses.
   - **Styles and machines** are explored with Gemini (`docs/images.md`; the batches `wasteland-styles-1`,
     `wasteland-machines-1` and `wasteland-sprites-1` on the wall).
3. **The map** (built with release 2). It is a screen of its own, opened from the header or with M. It charts the
   storm, the paths, the ground's marks and the nine places. Fog lifts where you walk and is kept. Tap a place, on
   the chart or in the list, to set a waypoint: a gold arrow on the screen's edge points to it, and a pillar of
   light stands over it until you arrive.
4. **Unlocks and machines**: work unlocks a point of interest, and a machine appears there.
5. **The studio machine**: operate a machine, play, commit, get an artifact.
6. **Carrying it home**: the artifact goes into the track's machine (the checklist, as screens).
7. **The museum, walked**: the artifacts hang inside.

## How it is built

- `static/checklist/wasteland/`:
  - `pix.js`: a 1-bit drawing surface, dither, noise;
  - `props.js`: everything standing, drawn by code;
  - `land.js`: the layout, the collision grid and the ground, drawn in 256 px chunks on first sight;
  - `hero.js`: the wanderer's frames and the scarf;
  - `main.js`: the loop, the input, the camera and the names of places.
- **Drawing.** The world is drawn at one art pixel per pixel into a canvas the size of the view (about 131 x 284
  art pixels on an iPhone), then scaled up by a whole number of device pixels, so every pixel stays square and a
  frame is cheap.
- **Tests.** `tests/ui/test_wasteland.py`.
