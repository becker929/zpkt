# 05 — Triage: soft delete, lists, bulk edit

The collection holds 3,451 sounds and 75 hours. Listening to all of it once is
the real task. Triage is the machinery for getting through it: every sound ends
up starred, discarded, or filed into a list, and a counter shows how far the
work has got.

## What triage means

A sound is **triaged** when it is in at least one of three states: soft
deleted, starred, or a member of any list. Nothing else counts. The header
shows triaged over total.

## Two different meanings of "deleted"

The schema already has a `deletion` table. It records a **path removed from
disk**, written by `dedupe --apply`. It is history, not a decision.

Soft delete is separate and new. It records a **sound the user does not want**,
attaches to the hash, touches no file, and is undone by restore. Do not
conflate them. A sound can be soft deleted while its bytes stay on disk, and a
path can be in `deletion` while the sound is starred.

Soft delete never removes a file. There is deliberately no path from this
feature to the filesystem. Sweeping discarded sounds to disk is a later
decision and is not built.

## Schema

```sql
CREATE TABLE soft_delete (
  hash       TEXT PRIMARY KEY REFERENCES blob(hash) ON DELETE CASCADE,
  deleted_at TEXT NOT NULL,
  note       TEXT
);

CREATE TABLE list (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE list_member (
  list_id  INTEGER NOT NULL REFERENCES list(id) ON DELETE CASCADE,
  hash     TEXT NOT NULL REFERENCES blob(hash) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  added_at TEXT NOT NULL,
  PRIMARY KEY (list_id, hash)
);
CREATE INDEX idx_list_member_hash ON list_member(hash);
```

`favorite` already exists and is the starred state. Every one of these keys on
the hash, so a decision made about one path applies to every copy of that
sound.

## Routes

| Route | Purpose |
|---|---|
| `PUT/DELETE /api/files/{hash}/deleted` | Soft delete and restore. |
| `GET/POST /api/lists` | List the lists; create one. |
| `GET/PATCH/DELETE /api/lists/{id}` | Read, rename, remove a list. |
| `PUT/DELETE /api/lists/{id}/members/{hash}` | Add or remove one sound. |
| `POST /api/bulk` | One action over many hashes. |
| `GET /api/triage` | Triaged count, total, and the split by state. |

`GET /api/files` gains `?deleted=`, taking `false` (the default), `true`, or
`any`. Soft-deleted sounds are hidden unless asked for, because the point of
discarding is to stop seeing it.

`POST /api/bulk` takes `{hashes: [...], action, list_id?}` where action is one
of `star`, `unstar`, `delete`, `restore`, `add_to_list`, `remove_from_list`.
Cap the batch at 1,000 hashes, apply it in one transaction, and return counts of
what changed rather than a per-hash result. Unknown hashes are skipped, not an
error: the client's view can lag a rescan.

## Interface

**Selection.** Rows take a checkbox on desktop and long-press on a phone. A
selection bar appears with the count and the bulk actions. Shift-click selects a
range. Clearing the filter clears the selection, because acting on rows that
scrolled out of a changed filter is how people delete the wrong thing.

**Soft delete and restore.** Discarding a sound removes it from the current view
with an undo affordance that lasts until the next action. A `deleted` filter
shows the discarded pile, where restore puts things back.

**Lists.** A view of lists, each with its member count and duration. Opening one
shows its sounds and plays them as a queue. Adding to a list from the selection
bar offers existing lists and a "new list" field.

**Triage counter.** In the header beside the collection totals: triaged over
total with a percentage. It is the progress bar for the whole project, so it
belongs on every view.

## Constraints

- Nothing here deletes a file. No route may remove audio from disk. The test
  asserting this already exists; extend it to the new routes.
- Every state keys on the hash, never a path.
- Bulk actions must be one transaction. A half-applied batch over 1,000 sounds
  is not recoverable by hand.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [04-segmentation.md](04-segmentation.md)
- **next**: [06-bakeoff-results.md](06-bakeoff-results.md)
