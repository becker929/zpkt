# 01 — Pinned spec

## Decisions made by Anthony

| Question | Answer |
|---|---|
| Scope | One application, built in stages. Stage 3 layers onto stage 2's waveform view. |
| Dedupe key | Exact bytes. BLAKE3 over the whole file. |
| Classifier | Build two or three approaches and compare. Do not pick one up front. |
| Stack | FastAPI backend, Next.js frontend. |

## Defaults chosen during execution

These were routine, so they were decided rather than asked.

**Project directory**: `audio-browser/` at the repo root. Self-contained, with
its own `pyproject.toml` and `.venv`, matching the convention that projects here
do not import across each other.

**Ports**: API on 8090, frontend on 3100. The vibe stack already uses 8283,
8080, 9010, and 3000. These two are free.

**Bind address**: `0.0.0.0`, no authentication. Tailscale is the security
perimeter. This is a real risk and is recorded below.

**Hash function**: BLAKE3 via the `blake3` package. Faster than SHA-256 and
listed first in the answer.

**Source of truth**: `compost/` is indexed in place, read-only. The application
never writes into it.

**Path storage**: paths are stored resolved through symlinks. `compost/` is a
symlink to `~/_tmsmsm/daw-library/compost`, so entries resolve to the real
location.

**Peaks cache**: waveform peaks are precomputed and stored in SQLite as int8
min/max pairs at 1,000 buckets per file. That is roughly 2 KB per file, so under
10 MB for the whole collection. Chosen because disk is nearly full.

**Audio formats**: the collection is 3,317 WAV, 1,008 AIF, 225 MP3, and about 30
M4A. Browsers play WAV, MP3, and M4A natively. AIF is transcoded to WAV on the
fly through ffmpeg during streaming.

## What counts as audio

Included: `.wav`, `.aif`, `.aiff`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.opus`.

Excluded: everything else. The collection also holds REAPER projects (`.rpp`,
`.rpp-bak`, `.rgt`), REAPER peak caches (`.reapeaks`), Ableton sets (`.als`) and
analysis files (`.asd`), Logic bundles (`.logicx`), plists, MIDI (`.mid`),
presets (`.fxp`), and images. MIDI is excluded because it holds no audio.

## The audio-library copy

`audio-library/` was created earlier in this session by copying `compost/`. Two
problems.

**It is redundant.** Sampled files hash identically to their `compost/`
counterparts. Both trees sit on the same physical volume, so the copy provides no
protection against disk failure. It costs 65 GB on a volume with 20 GB free.

**It contains DAW files.** The exclusion list used the wrong REAPER extension
(`.reaproject` instead of `.rpp`) and omitted several others. About 1,670
non-audio files came through, including 160 REAPER projects, 641 REAPER peak
caches, 247 plists, 132 MIDI files, and the Logic bundles.

**Resolution, as carried out.** The copy is kept. Its purpose is to be the tree
that work happens against, so the originals are never mangled. A copy on the
same volume does protect against that, which is the risk that matters here.

An earlier draft of this document argued for deleting the copy on the grounds
that it gave no protection against disk failure. That argument was answering the
wrong threat, and it was also wrong on the facts: there is no Time Machine
destination and no external volume attached, so the copy was the only redundancy
that existed.

What was done instead:

1. `compost/` was made read-only with `chmod -R a-w`. Immutability, not
   duplication, is what protects the originals. Undo with `chmod -R u+w`.
2. The DAW files were removed from the copy, which is what the original
   instruction asked for. 41 Logic bundles and 1,668 other non-audio files went.
   The copy fell from 65 GB to 35 GB and is now audio-only.
3. Free space went from 20 GB to 47 GB, which is enough for Stage 3.

Every byte removed was first verified to exist under `compost/`, so all of it is
recoverable by re-copying.

**Still outstanding.** There is no backup of this collection anywhere off this
disk. Both trees live on the same internal SSD. An external drive would fix
that, and would also be the right home for the working copy.

## Risks

**No authentication.** Anyone on the tailnet can read the whole collection and
change favorites. Acceptable if the tailnet is trusted. If it is shared, the
application needs auth before it is exposed.

**No off-disk backup.** This is the largest remaining risk. The collection
exists only on the internal SSD, in two trees. No Time Machine destination is
configured and no external volume is attached. An SSD failure loses everything,
including 305 Ableton sets that exist in `compost/` alone.

**Disk headroom.** Resolved for now: 47 GB free. Stage 3 model weights run
100 MB to 1 GB each and there are three of them, so watch this again before that
stage begins.

**Path stability.** Hashes are stable, paths are not. If files move inside
`compost/`, a re-scan updates the aliases. Favorites survive because they attach
to the hash.

**Repo git state.** The index still tracks hundreds of deleted SerumEvolver
files. `audio-library/` is not in `.gitignore`. Committing anything here needs
explicit paths and Anthony's approval.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [00-index.md](00-index.md)
- **next**: [02-hash-and-db.md](02-hash-and-db.md)
