# 11 — Overnight handoff

Written while Anthony slept, 2026-09-19. Updated as each step lands. Short
sentences. Read top to bottom.

## Status right now

Collage tracer bullet one is built on both sides and the adversarial usability
critic is running on it. Nothing from bullet one is committed yet. Bullets two
to five have not started.

## What shipped and was verified by me, not only reported

**Backend, bullet one.** 583 tests, `mypy --strict` clean. `collage` field on
the project with validation against the frozen set. `PUT /api/projects/{id}/collage`,
locked and atomic, 409 once committed. `GET /api/files/{hash}/slice?start=&end=`
returns 48 kHz stereo s16 WAV; I checked a real 4 s slice under ffprobe and the
byte count is exactly 4·48000·4+44. `enrich` exists as a placeholder column,
cap 1, no view. The board is **no longer blocked**: HW011 can commit forward
once it has a collage.

**Frontend, bullet one.** `/collage` opens HW011, empty canvas, picker over the
fifteen with preview, stamp, persist, play a region through Web Audio in 15 s
chunks. 177 Playwright tests passed, confirmed from the log. Screenshots in
`frontend/screenshots/collage-*.png`.

## One thing went wrong and was fixed

A live test wrote `"collage": {"regions": []}` into HW011 during cleanup. Column,
sounds and the `stored` commit were untouched; only that field and `updated_at`
changed. The file is tracked, so I restored it from git. Hash is back to
`f4a857da…`. The critic's first task is to make this structurally impossible:
live tests may read HW011 but every write goes to the mock server, and the live
project now hashes the file before and after and fails if it moved.

## Decisions I made for you

- **Stretch is varispeed.** Rate change, so pitch shifts. Usually the wanted
  sound on noise and texture. Pitch-preserving is a contained swap later.
- **Every stage owns its artefact.** `enrich` will copy the collage forward
  into its own field and edit only that, so the `collage` digest keeps meaning
  what it meant when taken.

## Carried forward into bullet two

Regions draw as label boxes. Trim needs you to see where the sound is inside a
region, so bullet two must draw the waveform with silence and span tinting
inside every region before adding handles.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [10-collage.md](10-collage.md)
- **next**: none.
