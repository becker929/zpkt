# audio-browser — index

A web application for browsing, playing, and tagging the audio collection in
`compost/`. Served over Tailscale. Built in three stages.

## Stages

| Doc | Stage | Delivers |
|---|---|---|
| [01-spec.md](01-spec.md) | Pinned spec | Decisions, defaults, open risks |
| [02-hash-and-db.md](02-hash-and-db.md) | Stage 1 | BLAKE3 index, SQLite schema, dedupe |
| [03-server-and-ui.md](03-server-and-ui.md) | Stage 2 | FastAPI + Next.js, streaming, favorites |
| [04-segmentation.md](04-segmentation.md) | Stage 3 | Speech/music/other span classifier bakeoff |
| [05-triage.md](05-triage.md) | Stage 4 | Soft delete, restore, lists, bulk edit, triage counter |
| [06-bakeoff-results.md](06-bakeoff-results.md) | Stage 3 result | What the three classifiers found, what they cost, which to use |
| [07-silence.md](07-silence.md) | Stage 5 | Silence measurement, auto-skip, sounding duration |
| [08-projects.md](08-projects.md) | Stage 6 | Projects as JSON files, the constrained board, commit and abandon |
| [09-swipe.md](09-swipe.md) | Stage 7 | Swipe as the only way to meet a sound; every browsing surface removed |
| [10-collage.md](10-collage.md) | Stage 8 | Collage: regions cut from sources, time down, tracks across, no grid |

## Summary

The collection holds about 4,600 audio files across `compost/`. Stage 1 hashes
every file and records it in SQLite. The hash is the identity of a sound. Paths
are aliases that point at a hash. This inverts the usual file-first model and
makes deduplication fall out for free.

Stage 2 serves that index as a browsable, streamable playlist. Favorites attach
to the hash, so marking one copy marks every alias.

Stage 3 segments audio into spans labelled speech, music, or other, so the
waveform view can colour-code them. Three approaches get built and compared
before one is chosen.

## Status

**Stage 1 is complete.** 3,451 unique sounds indexed, 75 hours 38 minutes, from
8,277 paths across two roots. 68 tests pass and `mypy --strict` is clean.

**Stage 2 is in progress.** Backend and frontend are being built in parallel
against the route table in [03-server-and-ui.md](03-server-and-ui.md).

**Stage 3 has not started.**

## Disk, resolved

The disk problem is fixed. `audio-library/` is kept as a working copy, so that
work never touches the originals. It was reduced from 65 GB to 35 GB by removing
41 Logic project bundles and 1,668 other non-audio files, which should never
have been copied. Free space went from 20 GB to 47 GB.

`compost/` is now read-only at the filesystem level (`chmod -R a-w`). That is
what protects the originals. The copy protects the workflow.

Pruning after the deletion removed 867 aliases and zero blobs, which proves no
sound became unreachable: every file removed from the copy still resolves
through its original.

One consequence: Logic and REAPER projects now exist only under `compost/`,
which is read-only. Opening one to edit needs `chmod -R u+w` on that project
first.

## Known duplication, deliberately left alone

3.94 GB inside the copy is genuinely redundant: 285 sounds with 329 extra
copies. It is not removed, because choosing which path survives changes how the
library is organised and should be done by ear in the Stage 2 detail view.

An earlier reading of the same data claimed 33 GB of duplication. That was
wrong. Most of it was Logic freeze and bounce files inside project bundles,
which are project internals rather than stray copies.

## Navigation

- **next**: [01-spec.md](01-spec.md)
