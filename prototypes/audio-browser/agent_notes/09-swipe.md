# 09 — Swipe, and the removal of every other surface

## The change in one sentence

The collection stops being a library you browse and becomes a queue you answer.

## Swipe is the app view for `stored`

`stored` is the column. Swipe is how you work it. One sound at a time, looping,
and you cannot move on without deciding.

- One sound fills the view. It loops until you act.
- Silence is skipped, so a 5 minute stem with 40 seconds of sound takes 40
  seconds. A quarter of this collection is dead air; skipping it is what makes
  a one-pass listen possible at all.
- The waveform shows YAMNet spans, because a glance at where the sound actually
  happens speeds the decision.
- **Two actions only: take it into the current project, or discard it.**

### There is no third action, deliberately

"Not for this project but keep it" is deferral, and deferral is what we removed
favourites for. A sound you do not take is discarded. Discard is reversible —
that is what restore is for — so the cost of being decisive is low and the cost
of being indecisive is the whole problem.

## One lane

`stored` holds **one** uncommitted project. There is no picking which project a
sound goes into, because there is only ever one on the bench.

A new project cannot be born in `stored` until the current one commits, and a
commit needs somewhere to go.

## Encumbrance

Past a threshold of sounds, the project is marked **encumbered**: it has more
material than a track needs. This is friction, not restriction. Adding still
works, the mark stays until the count comes down, and it is visible every time
the project is on screen.

Default threshold: **16 sounds**. A hard techno track is a kick, a rumble, a few
percussive textures, two or three atmospheres and some impacts. Past sixteen you
are collecting, not building. Configurable in the same place as the caps.

## The pipeline, and where it blocks

Two columns exist right now:

| Column | View | Cap |
|---|---|---|
| `stored` | swipe | 1 |
| `collage` | none yet | 1 |

`enrich` is not built and is not a column yet.

The sequence, which is correct behaviour rather than a bug:

1. `stored` holds an uncommitted project.
2. It commits. The sound set freezes, the project moves to `collage`, the swipe
   lane is free.
3. A new project is born in `stored`.
4. That project **cannot commit**: `collage` is full at its cap of one.
5. `collage` commits its own stage — and has nowhere to go, because no column
   follows it. It stays, holding its lane.
6. **Blocked.** Nothing can move. The board says so plainly, naming what is
   missing: the next column does not exist.

This is the constraint reaching its natural limit. The system physically will
not let you accumulate more than one finished stage ahead of the work you have
actually built the tools to do.

**Abandon is the only legal escape**, and that is why it exists. Abandoning the
project in `collage` frees the lane and lets `stored` commit again. The
constraint bites, and there is exactly one pressure valve, and using it means
admitting an idea is dead. That is the right price.

## Every other surface is removed or narrowed

**Removed outright:**

- **Favourites.** A star means "decide later", which a triage lane must not
  offer.
- **Standalone lists.** Project membership replaces them. A list that is not a
  project is a maybe-pile with no exit.
- **The playlist view.** Passive listening. Sixty-five hours can pass through it
  and decide nothing.
- **The duplicates view.** Library maintenance, already done.
- **Sort by size and alias count.** Nobody chooses a sound because it has four
  paths.
- **Alias paths in the detail view.** Content addressing made them correct, not
  interesting.

**Narrowed:**

- **The list view now shows only what has already been swiped.** Filters: taken
  or discarded, which project it went into, and by name. It is a record of
  decisions, not a catalogue.
- **The search view shows only matches.** Empty query, empty view.

Between them there is **no surface that shows the undecided collection**. That
is the point. The only way to meet an unheard sound is to swipe it.

## Constraints

- No route may delete audio. The two tests asserting this must keep passing.
- Discard is soft delete, keyed on hash, reversible.
- Mobile is the primary target; swipe is a one-thumb interface.
- Silence skipping and span tinting are already built; use them, do not rebuild.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [08-projects.md](08-projects.md)
- **next**: none.
