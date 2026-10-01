# 08 — Projects and the constrained board

## What this is for

This is not a general purpose audio platform. It exists to produce hard
industrial techno. Where a decision could go either way, pick the one that
serves that music. Tempo, transients, and weight matter; general-purpose
flexibility does not.

## The workflow

Three columns, each one an app view:

| Column | What happens there | Committing it freezes |
|---|---|---|
| **stored** | Assign sounds from the library. This is the browser that exists today. | the sound set |
| **collage** | Cut, move, balance. | the arrangement |
| **enrich** | Effects. | the treatment |

Behind `stored` sits the whole library, 3,451 sounds. That is the unbounded
universe, along with everything upstream of it — recording, clipping,
synthesis. Scarcity starts at the first column, not before it.

A project leaving `enrich` is **released**. It is off the board and no longer
occupies a slot anywhere.

## The limit is friction, not restriction

Each column has its own cap. The default is 3, and it is meant to be turned
down: 2, or 1, are reasonable and the configuration should make that a one-line
change.

Exceeding a cap is **possible but deliberately uncomfortable**. The board does
not silently refuse. It states the cap, requires an explicit override, and then
keeps showing the column as over its limit until the count comes back down.
Someone who overrides should feel it every time they open the board. A hard
block would just teach people to edit the config.

## Commit is a boundary, not a place

Commit is **not a column**. It is the interface at a column's edge: the moment a
column gives a project up to the next one. Every column has its own commit, and
each freezes that column's own artifact.

Committing out of `stored` freezes the sound set. From then on the project can
never gain or lose a sound, in any later column. Committing out of `collage`
freezes the arrangement. Out of `enrich`, the treatment — and the project is
released.

**Committed is not saved.** Saving happens constantly. Committing is a promotion
and it is one-way: nothing in the app reopens a frozen stage.

Each commit frees a slot in the column it leaves and takes one in the column it
enters.

### Downstream capacity gates promotion

If the next column is at its cap, the commit does not go through. This is the
point of the constraint rather than a limitation of it: you cannot keep
gathering material when the collage bench is already full. Finish something
downstream first.

An over-cap commit gets the same treatment as everything else here — possible,
explicit, and uncomfortable. See "friction, not restriction".

## Abandon is the other exit

Commit is not the only way off the board, and it must not be. If it were, a
project you no longer believe in would hold its slot forever, and the only
escape would be to commit something you do not want — which would empty the word
"committed" of meaning. At a cap of one or two, that turns friction into a trap.

**Abandon** releases a slot without promoting anything. The project leaves the
board and is kept, not deleted, marked with when it was abandoned, the column it
was in, and an optional reason. What you tried is worth keeping; this music is
made by discarding most of what you start.

Abandoning is lighter than committing, because it is reversible. It asks for
confirmation, but it does not freeze anything and it appends nothing to the
commit chain.

**Revive** brings an abandoned project back to the column it left. It takes a
slot like anything else, and is refused when that column is full, with the same
override treatment. Reviving is not free — the cost is the slot, which is
exactly the right price.

A revived project keeps every commit it already had. One abandoned out of
`collage` comes back to `collage` with its sound set still frozen.

### Each commit is verifiable

Every stage records a digest of what it froze, so the project carries a chain of
them. For `stored` that is the BLAKE3 of the member hashes, sorted and joined by
newline. Later stages digest their own artifact the same way.

Because the sound set is content hashes, this holds for years: the manifest
still resolves after files move, get renamed, or the working copy is rebuilt. If
a project file is hand-edited after a commit, the digest no longer matches and
the app can say so. The freeze is a fact that can be checked rather than a rule
the app promises to keep.

## A project is a file

Projects live as real JSON documents in `audio-browser/projects/`, one file per
project. The file is the truth. SQLite indexes them so the board can be drawn
without reading every file, but the index is a cache and can be rebuilt from the
directory at any time. If the two disagree, the files win.

```jsonc
{
  "schema_version": 1,
  "id": "2026-09-16-rust-and-rebar",   // slug, also the filename
  "name": "rust and rebar",
  "column": "stored",                   // stored | collage | enrich | released
  "created_at": "2026-09-16T21:04:00Z",
  "updated_at": "2026-09-16T21:40:00Z",
  "notes": "",

  // Non-null means off the board, holding no slot. `column` still records
  // where it was, which is what revive needs. Cleared by revive.
  "abandoned": null,
  // { "at": "2026-09-16T22:00:00Z", "from": "collage", "reason": "" }

  // One entry per stage that has been committed, in order. Append only.
  // Abandoning appends nothing.
  "commits": [
    // { "column": "stored", "at": "…", "digest": "blake3…" }
  ],

  "sounds": [
    { "hash": "fa30…", "added_at": "2026-09-16T21:10:00Z", "role": null, "note": "" }
  ]
}
```

`commits` is the chain. A project in `collage` has one entry, for `stored`. Its
sound set is frozen because that entry exists, not because of any flag.
Membership edits are refused whenever a `stored` commit is present.

`role` is a free slot for the later columns to use — `kick`, `rumble`, `texture`
— and is null until something sets it.

## One schema, two languages

The user named Zod, so **Zod is the source of truth**. It lives at
`frontend/lib/project.ts`. A script emits a JSON Schema to
`audio-browser/schemas/project.schema.json`, and Python validates against that
generated file with `jsonschema`. Neither language hand-maintains a second copy.

Each view takes what it needs from the shared model and ignores the rest. A
view must not widen the schema to suit itself.

## Routes

| Route | Purpose |
|---|---|
| `GET /api/projects` | Every project, with column and counts. |
| `POST /api/projects` | Create. Refuses past the cap unless `override: true`. |
| `GET/PATCH /api/projects/{id}` | Read, rename, edit notes. **Moving column is refused (409)** — commit is the only way a project advances, or the freeze could be sidestepped by editing a field. |
| `POST /api/projects/{id}/abandon` | Leave the board, free the slot, keep the file. Appends nothing to `commits`. |
| `POST /api/projects/{id}/revive` | Return to the column it left. **409 when that column is at cap**, unless `override: true`. |
| `POST /api/projects/{id}/commit` | Freeze this column's artifact, append to `commits`, advance. **409 when the next column is at cap**, unless `override: true`. |
| `PUT/DELETE /api/projects/{id}/sounds/{hash}` | Add or remove. **409 once a `stored` commit exists.** |
| `GET /api/board` | Columns, caps, occupancy, and which are over. |

The existing `list` tables stay as they are. A project references sounds
directly by hash; it does not wrap a list. Lists are for triage, projects are
for making something.

## Interface

The board is a view of columns with their caps shown as occupancy, not as a
number buried in a tooltip. An over-limit column stays visibly wrong.

The triage ratio and the board's occupancy belong side by side in the header.
They are the same discipline at two scales: finish what you started before
starting more.

In the browser, the selection bar gains "add to project", offering only projects
whose sound set is still open — on the board, in `stored`, with no `stored`
commit. A project further down the board, or abandoned, cannot take new sounds,
so it must not appear as though it could.

Abandoned and released projects live below the columns, not inside them. They
are visible, because the record of what was tried is worth seeing, but they hold
no slot and are plainly not in play. Reviving is offered from there.

## Scope

This document covers the spine: the model, the file format, the board, the caps,
commit, and wiring `stored` to the existing browser. `collage` and `enrich` are
real applications in their own right and are not built here. They appear as
columns a project can move to, and their views come later.

## Constraints

- No route may delete audio. The two tests asserting this must keep passing.
- Committed projects reject membership changes at the API, not only in the UI.
- The files win over the index, always.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [07-silence.md](07-silence.md)
- **next**: none.
