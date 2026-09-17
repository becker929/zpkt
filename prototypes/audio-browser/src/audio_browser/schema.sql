-- audio-browser schema.
--
-- The hash is the identity of a sound. A path is only an alias that points at a
-- hash. Every decision attaches to the hash, so answering one copy answers every
-- duplicate.

CREATE TABLE IF NOT EXISTS blob (
  hash        TEXT PRIMARY KEY,   -- blake3 hex digest of the whole file
  size_bytes  INTEGER NOT NULL,
  duration_s  REAL,               -- NULL until probed
  sample_rate INTEGER,
  channels    INTEGER,
  codec       TEXT,
  peaks       BLOB,               -- int8 min/max pairs, NULL until computed
  probed_at   TEXT
);

CREATE TABLE IF NOT EXISTS alias (
  id       INTEGER PRIMARY KEY,
  hash     TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  path     TEXT NOT NULL UNIQUE,  -- absolute, symlinks resolved
  root     TEXT NOT NULL,         -- scan root this was found under
  filename TEXT NOT NULL,
  ext      TEXT NOT NULL,
  mtime    REAL NOT NULL,
  seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alias_hash ON alias(hash);
CREATE INDEX IF NOT EXISTS idx_alias_filename ON alias(filename);
CREATE INDEX IF NOT EXISTS idx_alias_root ON alias(root);

-- A star. The routes that wrote and read this are gone: a star meant "keep
-- this, decide later", and the queue has two answers and no later. The table
-- and its rows stay because removing a route is one decision and destroying
-- data is another, and only the first one was made.
CREATE TABLE IF NOT EXISTS favorite (
  hash       TEXT PRIMARY KEY REFERENCES blob(hash) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  note       TEXT
);

CREATE TABLE IF NOT EXISTS tag (
  hash TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  name TEXT NOT NULL,
  PRIMARY KEY (hash, name)
);

-- Every path the dedupe command removed. This is the durable memory of a
-- deletion, so a sound can still say "I was also seen here, until this date".
--
-- Two deliberate omissions:
--
-- * No foreign key to blob(hash). A rescan prunes blobs that lost every alias,
--   and ON DELETE CASCADE would then erase the record of why they vanished.
--   The record has to outlive the blob row.
-- * No foreign key to alias(path). The alias row is gone by the time this row
--   is written; that is the whole point.
--
-- `path` is unique. A row means "this path was deleted", not "a deletion event
-- happened", so re-deleting the same path after it was restored updates the
-- timestamp instead of piling up rows.
CREATE TABLE IF NOT EXISTS deletion (
  id         INTEGER PRIMARY KEY,
  hash       TEXT NOT NULL,          -- blake3 digest the path used to hold
  path       TEXT NOT NULL UNIQUE,   -- absolute, symlinks resolved
  root       TEXT NOT NULL,          -- root the path was found under
  deleted_at TEXT NOT NULL,          -- ISO 8601 UTC
  reason     TEXT NOT NULL           -- short phrase, e.g. 'redundant copy'
);
CREATE INDEX IF NOT EXISTS idx_deletion_hash ON deletion(hash);

-- A sound the user does not want. This is a decision, not a filesystem event.
--
-- It is not the `deletion` table above and must never be confused with it.
-- `deletion` records a path that was removed from disk. `soft_delete` records a
-- judgement about a sound: the bytes stay exactly where they are, every alias
-- stays on disk, and the only effect is that the list view stops showing it.
-- Restore is a DELETE of this row. Both tables can hold the same hash at once:
-- a redundant copy can be swept from disk while the sound itself is still
-- wanted, and a sound can be discarded while every copy of it survives.
--
-- No code anywhere turns a row here into a filesystem operation.
CREATE TABLE IF NOT EXISTS soft_delete (
  hash       TEXT PRIMARY KEY REFERENCES blob(hash) ON DELETE CASCADE,
  deleted_at TEXT NOT NULL,        -- ISO 8601 UTC
  note       TEXT
);

-- A named collection of sounds. Project membership replaced this: a list that
-- is not a project is a maybe-pile with no exit. No route reads or writes these
-- two tables any more, and their rows are kept exactly as they were.
CREATE TABLE IF NOT EXISTS list (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

-- Membership keys on the hash, like every other decision here. `position` is
-- the order the list played in.
CREATE TABLE IF NOT EXISTS list_member (
  list_id  INTEGER NOT NULL REFERENCES list(id) ON DELETE CASCADE,
  hash     TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  added_at TEXT NOT NULL,
  PRIMARY KEY (list_id, hash)
);
CREATE INDEX IF NOT EXISTS idx_list_member_hash ON list_member(hash);

-- Labelled regions of a sound. Stage 3 writes these; stage 2 only reads them,
-- so the table is normally empty and GET /api/files/{hash}/spans returns [].
--
-- `method` is kept per row rather than folded away, so several classifiers can
-- run over the same sound and be compared side by side in the interface.
CREATE TABLE IF NOT EXISTS span (
  id         INTEGER PRIMARY KEY,
  hash       TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  method     TEXT NOT NULL,   -- 'yamnet' | 'pyannote' | 'clap'
  start_s    REAL NOT NULL,
  end_s      REAL NOT NULL,
  label      TEXT NOT NULL,   -- 'speech' | 'music' | 'other'
  confidence REAL,
  detail     TEXT             -- finer label, e.g. 'drum kit', 'laughter'
);
CREATE INDEX IF NOT EXISTS idx_span_hash_method ON span(hash, method);

-- Bookkeeping for stage 3: one row per sound per classifier.
--
-- It answers a question the `span` table cannot. A sound with no rows in `span`
-- for a method might never have been tried, or might have been tried and found
-- to hold nothing worth a span. Without this table a restart would redo the
-- second kind forever, and a run over 46 hours of audio has to be restartable.
--
-- It is also where the bakeoff's timing and memory numbers come from, so the
-- report quotes measurements rather than estimates.
CREATE TABLE IF NOT EXISTS segment_run (
  hash       TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  method     TEXT NOT NULL,
  status     TEXT NOT NULL,      -- 'ok' | 'failed'
  spans      INTEGER NOT NULL,   -- how many rows it wrote into `span`
  audio_s    REAL NOT NULL,      -- seconds of audio the classifier saw
  elapsed_s  REAL NOT NULL,      -- wall seconds, decode included
  peak_rss_b INTEGER,            -- process peak resident memory when measured
  error      TEXT,               -- why it failed, when it did
  ran_at     TEXT NOT NULL,      -- ISO 8601 UTC
  PRIMARY KEY (hash, method)
);
CREATE INDEX IF NOT EXISTS idx_segment_run_method ON segment_run(method, status);

-- Dead air, measured once per sound with
-- `ffmpeg -af silencedetect=n=-50dB:d=0.4`.
--
-- A quarter of the collection is silence: 11.5 hours of 45.8. The player skips
-- it and the statistics stop counting it as listening time, so every length the
-- interface shows is a sounding length.
--
-- These two tables were first written by hand, straight into the live index.
-- They are here so a fresh index has them and so `audio-browser silence` can
-- fill them again from nothing. `CREATE TABLE IF NOT EXISTS` leaves the rows
-- that already exist exactly as they are.
--
-- No foreign key to blob(hash). The measurement is expensive and a rescan that
-- briefly loses an alias must not throw it away.
CREATE TABLE IF NOT EXISTS silence (
  hash        TEXT PRIMARY KEY,
  max_db      REAL,            -- peak level over the whole file
  mean_db     REAL,
  silent_s    REAL,            -- total seconds in gaps of 0.4 s or more
  duration_s  REAL,            -- wall duration ffmpeg saw
  silent_frac REAL,
  measured_at TEXT NOT NULL    -- ISO 8601 UTC
);

-- Every gap down to 0.4 seconds. The floor the player skips at is applied at
-- read time, not here, so it stays a setting rather than a property of the data.
--
-- `start_s` is part of the key: one sound cannot have two gaps starting at the
-- same instant, and re-measuring the same sound replaces rather than doubles.
CREATE TABLE IF NOT EXISTS silence_interval (
  hash    TEXT NOT NULL,
  start_s REAL NOT NULL,
  end_s   REAL NOT NULL,
  PRIMARY KEY (hash, start_s)
);
CREATE INDEX IF NOT EXISTS idx_silence_interval_hash ON silence_interval(hash);

-- The board's cache of `audio-browser/projects/`.
--
-- The files are the truth. Every row here is derived from one JSON document and
-- can be thrown away and rebuilt from the directory. `mtime_ns` and
-- `size_bytes` are how a stale row is spotted: a file whose stamp differs from
-- the row is re-read before anything is answered from it, so the cache can
-- never outvote its source.
--
-- `document` is the file's own bytes, kept so a board can be drawn without
-- opening 40 files. It is a copy, never an original.
--
-- A file that does not validate still gets a row, with `valid = 0` and the
-- reason in `problem`. Dropping it would let one junk key free a slot, which is
-- a cap bypass that needs no override.
CREATE TABLE IF NOT EXISTS project (
  id          TEXT PRIMARY KEY,   -- the slug, which is also the filename
  path        TEXT NOT NULL,
  mtime_ns    INTEGER NOT NULL,
  size_bytes  INTEGER NOT NULL,
  valid       INTEGER NOT NULL,   -- 1 when the document matches the schema
  problem     TEXT,               -- why it does not, when it does not
  -- stored | collage | enrich | released, or NULL. The board is `stored` and
  -- `collage`; `enrich` is in the plan and in the document schema, so a file
  -- may name it, but there is no such column and it holds no slot.
  placement   TEXT,
  abandoned   INTEGER NOT NULL DEFAULT 0,
  name        TEXT,
  created_at  TEXT,
  updated_at  TEXT,
  document    TEXT NOT NULL,      -- the file as it was read
  sound_count INTEGER NOT NULL DEFAULT 0,
  indexed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_placement ON project(placement, abandoned);

-- One row per sound in a project, in document order. Membership keys on the
-- hash, like every other decision in this index, so a project holds sounds and
-- not paths.
--
-- This is half of the triage counter and half of the swipe queue: a sound is
-- answered when it is in `soft_delete` or here, and the queue is every sound in
-- neither. The rows are derived from the project files and are rebuilt from
-- them whenever one changes.
CREATE TABLE IF NOT EXISTS project_sound (
  project_id TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  hash       TEXT NOT NULL,
  position   INTEGER NOT NULL,
  added_at   TEXT NOT NULL,
  role       TEXT,
  note       TEXT,
  PRIMARY KEY (project_id, hash)
);
CREATE INDEX IF NOT EXISTS idx_project_sound_hash ON project_sound(hash);

CREATE VIRTUAL TABLE IF NOT EXISTS alias_fts USING fts5(
  filename, path, content='alias', content_rowid='id'
);

-- alias_fts is an external-content table. SQLite does not keep it in sync on its
-- own, so these triggers mirror every alias write into the index.
CREATE TRIGGER IF NOT EXISTS alias_fts_ai AFTER INSERT ON alias BEGIN
  INSERT INTO alias_fts(rowid, filename, path)
  VALUES (new.id, new.filename, new.path);
END;

CREATE TRIGGER IF NOT EXISTS alias_fts_ad AFTER DELETE ON alias BEGIN
  INSERT INTO alias_fts(alias_fts, rowid, filename, path)
  VALUES ('delete', old.id, old.filename, old.path);
END;

CREATE TRIGGER IF NOT EXISTS alias_fts_au AFTER UPDATE ON alias BEGIN
  INSERT INTO alias_fts(alias_fts, rowid, filename, path)
  VALUES ('delete', old.id, old.filename, old.path);
  INSERT INTO alias_fts(rowid, filename, path)
  VALUES (new.id, new.filename, new.path);
END;
