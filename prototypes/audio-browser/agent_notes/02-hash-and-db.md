# 02 — Stage 1: hash index and database

Build the index that everything else reads. No web server yet. This stage ends
with a populated SQLite file and a command-line report of duplicates.

## Deliverables

- `audio-browser/pyproject.toml`, uv-managed, Python 3.12+.
- `src/audio_browser/schema.sql` — the tables below.
- `src/audio_browser/scan.py` — walk roots, hash, probe, upsert.
- `src/audio_browser/peaks.py` — waveform peak extraction.
- `src/audio_browser/cli.py` — `scan`, `dupes`, `stats` commands.
- `tests/` — pytest, offline, using small generated WAV fixtures.

## Schema

The hash is the primary key of a sound. A path is an alias pointing at a hash.

```sql
CREATE TABLE blob (
  hash        TEXT PRIMARY KEY,   -- blake3 hex digest of the whole file
  size_bytes  INTEGER NOT NULL,
  duration_s  REAL,               -- NULL until probed
  sample_rate INTEGER,
  channels    INTEGER,
  codec       TEXT,
  peaks       BLOB,               -- int8 min/max pairs, NULL until computed
  probed_at   TEXT
);

CREATE TABLE alias (
  id       INTEGER PRIMARY KEY,
  hash     TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  path     TEXT NOT NULL UNIQUE,  -- absolute, symlinks resolved
  root     TEXT NOT NULL,         -- scan root this was found under
  filename TEXT NOT NULL,
  ext      TEXT NOT NULL,
  mtime    REAL NOT NULL,
  seen_at  TEXT NOT NULL
);
CREATE INDEX idx_alias_hash ON alias(hash);
CREATE INDEX idx_alias_filename ON alias(filename);

CREATE TABLE favorite (
  hash       TEXT PRIMARY KEY REFERENCES blob(hash) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  note       TEXT
);

CREATE TABLE tag (
  hash TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  name TEXT NOT NULL,
  PRIMARY KEY (hash, name)
);

CREATE VIRTUAL TABLE alias_fts USING fts5(
  filename, path, content='alias', content_rowid='id'
);
```

Stage 3 adds a `span` table. It is documented in
[04-segmentation.md](04-segmentation.md).

## Scanning

Walk each root. For every file whose extension is in the audio allowlist from
[01-spec.md](01-spec.md#what-counts-as-audio):

1. Resolve the path through symlinks. Skip if already recorded with an unchanged
   size and mtime.
2. Hash the bytes with BLAKE3, reading in 1 MB chunks so large WAVs do not load
   into memory.
3. Upsert the `blob` row, then upsert the `alias` row.
4. Probe with `ffprobe` for duration, sample rate, channels, and codec. Only
   probe when the blob is new, since probing is the slow part.

Hashing is I/O-bound and probing is process-bound, so run them in a thread pool.
Eight workers is a reasonable default. Write to SQLite from a single thread to
avoid lock contention; workers hand results back through a queue.

Enable `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`. The scan is
restartable, so a crash costs only the unflushed batch.

## Peaks

Decode with ffmpeg to mono 22.05 kHz signed 16-bit, then reduce to 1,000 buckets.
Each bucket stores the minimum and maximum sample as two int8 values scaled from
the int16 range. That is 2,000 bytes per file.

Peaks are computed lazily on first request in stage 2, not during the initial
scan. Decoding 4,600 files up front would take hours and is not needed to prove
the index works.

## Roots to scan

Scan both `compost/` and `audio-library/`. Scanning both is the point: it proves
whether the trees are identical. Roots are configured in `config.toml`, not
hardcoded.

## The `dupes` report

Print every hash with more than one alias, grouped, with the total wasted bytes.
Then print a summary answering the question that matters: how many
`audio-library/` blobs have a `compost/` twin, and how many do not.

If that second number is zero, `audio-library/` is fully redundant and can be
deleted. Do not delete it. Report the number and stop.

## Acceptance

- `uv run audio-browser scan` completes over both roots.
- `uv run audio-browser dupes` reports the redundancy count.
- `uv run pytest tests/ -v` passes offline, with no access to the real library.
- Re-running `scan` is a no-op and finishes in seconds.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [01-spec.md](01-spec.md)
- **next**: [03-server-and-ui.md](03-server-and-ui.md)
