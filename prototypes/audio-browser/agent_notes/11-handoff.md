# 11 — Overnight handoff

Written while Anthony slept, 2026-09-19. Updated as each step lands. Short
sentences. Read top to bottom.

## Status right now

Bullet one — choose a sound and stamp it — is reviewed and committed as
`aa6807a` on `feature/audio-browser`. Bullet two — trim — is reviewed and
committed as `3a1ae38`. Bullet three — snip — is built and verified, and its
critic is running; it is not committed. Bullets four and five have not started.

## Bullet three — snip — built, verified, under review

The builder delivered: snip as a mode entered by a chunky button; handles
hidden while it is on and the bar saying so; drag down a region to paint the
span that goes, in trim's striped language; release makes two regions, the
first keeping `id` and `at_s`, the second placed where its material already
sounded so a snipped gap stays a gap; a half that would fall under 0.25 s
extends the removal to that edge; one `PUT`, one undo; the first half taken up
afterwards with live handles, which is the close-handles rule doing its job.

Verified by me, not the builder: **219 passed, 2 skipped, 0 failed** in the
foreground, HW011 unchanged, typecheck clean, no server or runner left behind.

**The thing the critic must attack first.** When a snip would leave nothing,
the band turns amber and release **removes the region**. The builder named it
plainly: this is the only delete gesture on the surface, and its only
confirmation is that band. A region is a cut made by ear. If the undo stack
does not survive a reload, a mis-drag in snip mode destroys work with an amber
flash. The critic is measuring that and proposing the smallest thing that makes
it deliberate without becoming an "are you sure".

**Design questions the builder raised, for you:** the two halves share a name
and a hue and only position and waveform tell them apart; on a 10 px region
every snip is a whole snip; snipping the start keeps the material's moment
while trimming the start keeps `at_s`, so the two gestures disagree about
whether material moves — the builder chose what-you-see for snip and flagged
it rather than deciding.

Before committing bullet two I re-ran everything myself: 205 passed, 2
skipped, 0 failed in the foreground; HW011 unchanged; and a bare listener I
put on 3101 made a one-test run exit in one second naming its PID. Those
three facts are mine, not the critic's.

## The critic's findings on bullet one

Fixed before commit:

- A fourth track landed off-screen: three tracks are 384 of 393 px, so a stamp
  in the 9 px sliver created a track you could not see. It now scrolls into view.
- Two short cuts drew on top of each other because both were padded to 44 px.
- TypeScript accepted a `collage` on a `stored` document; Python refused it.
  They agree now, and the schema check covers it.

Reported, and carried into bullet two: the stamp bar's wording is not true
(tapping a region plays, it does not stamp); undo is one level and says
nothing; the header shows library hours on this screen, which the no-seconds
rule forbids; padding lies about length once trim makes short cuts.

Reported, not fixed: iOS pulls a tap within about 15 px onto a nearby region,
so a gap narrower than a thumb cannot be stamped into. Real WebKit behaviour.
Mitigation would be wider gutters or a long-press to force a stamp.

## Bullet two — trim — built, not yet reviewed or committed

The builder delivered: the waveform drawn vertically inside every region with
silence and span tinting; regions at true length with 64×44 handles outside
each end; tap a handle, drag to trim; `at_s` holds so a region keeps its place
while its length changes; 0.25 s minimum length; a 20-deep undo that says how
many steps it holds; the stamp bar's wording made true; library hours hidden in
the header on this screen.

One real WebKit finding, worth keeping: Safari synthesises `click` at an
*adjusted* point, so a tap squarely inside a 12 px region was delivered to the
44 px handle beside it. Taps are now read from `pointerdown`/`pointerup` pairs,
which carry the true point.

**What I saw in the screenshots that the critic must attack first.** Two short
regions on one track collapse into a pile of overlapping handles thinner than a
thumb, and the regions themselves become slivers you cannot tap to play. Snip
creates exactly that seam every time. This has to be solved before bullet
three, not after it.

**Verified.** My own foreground run: **200 passed, 2 skipped, 0 failed**, and
HW011 held at `f4a857da…` through the live project. Bullet two is green.

**The stall, diagnosed and fixed.** Orphaned `next dev` servers on the
test-only ports 3101–3103 survived the builder's killed runs, and
`playwright.config.ts` had `reuseExistingServer: true` outside CI on those
three entries. So every later run attached to a wedged orphan and waited
forever with an empty log — that is what stalled three agents in a row and my
own first run. Killing the orphans made the same suite pass in 3.5 minutes.
The three test servers are now `reuseExistingServer: false`. **That turned out
to be necessary but not sufficient**, and I had written here that it fixed
the hang before it was proven. The first critic proved the opposite: with a
bare TCP listener holding 3101, a one-test run sat for 2 hours 56 minutes.
Playwright's readiness check only needs the port to accept a connection, which
a bare listener does, so it believes the server is up and every test then hangs
on navigation. The real fix is a preflight that checks each test port is free
— not merely connectable — and exits naming the holder's PID, plus an explicit
`timeout` on each `webServer`. The second critic is implementing and timing it.
The user's server on 3100 is not a `webServer` entry and was never touched.

Lesson for me, recorded so I stop doing it: do not write "fixed" into this
note until the fix is proven. Twice tonight I wrote the conclusion first.

**Process fix for every later brief.** Three agents in a row ended their turn
while a backgrounded test suite was still running, and delivered no report.
Suites run in the foreground with a long timeout, never backgrounded.

## The critic's findings on bullet two

**A held test port now fails in about a second.** `reuseExistingServer:
false` was not enough: Playwright probes each `webServer` URL with an HTTP
GET that has no timeout, before the entry's own `timeout` exists and before
`globalSetup`. A bare TCP listener on 3101 accepts the connection and never
answers, and the runner sat for three hours with one debug line. The check
now runs as `playwright.config.ts` loads, the only point earlier than that
probe: `e2e/free-ports.ts` asks `lsof` who is listening on 3101–3103 and
fails naming the port, the PID and the command. Measured: 1.1 s to fail with
the port held; 15 s to start the servers and pass with it free. 3100 is not
checked.

**The pile is gone.** Measured on the phone descriptor before the fix: two
one-second cuts half a second apart gave a region's own two handles a 9.5 px
overlap, and a real touch at a region's centre selected a handle instead of
playing it. The fix is one rule, not a special case for short regions:

- Only the region taken up has handles: two, a full thumb each, outside its
  box, raised over its neighbours. There is nothing else to pile.
- Every region has a grab: an invisible hit area that reaches out from the
  box until it is a thumb tall, and never past the middle of the gap to a
  neighbour, so grabs never overlap. `grabZone` in `lib/collage.ts`.
- A tap on a region plays it and takes it up. A thumb on a handle drags at
  once; a tap on a handle selects it (for the keyboard now, stretch later).
- A tap on the blank puts the region down and, with a sound chosen, stamps.
  Stamp, listen, stamp is the loop a phone lives in, and a tap that only let
  go made the second stamp a dead tap every time.
- Letting go of the start handle scrolls the canvas by the drag, so the
  handle stays under the thumb instead of jumping back to the top of the box.
- Undo keeps the handle selected if its region is still there.

Tried against it: a neighbour under a raised handle is still reachable at
its flanks; slow taps, taps that travel, taps across the seam between box
and handle; a fifteen-minute region at 9000 px draws at both ends under the
8192 px cap; trim, stamp, trim, then undo three times; every `aria-label`
and `title` on the view grepped for a time or a level.

**Design questions for Anthony.** Trim is now tap the region, then drag its
handle; the spec says tap the handle. A tap on the blank beside a raised
region's handle stamps rather than only letting go; undo takes it back. An
unselected region shows no hint that it can be trimmed until it is tapped.
The first region on a canvas still sees its start handle jump back by
whatever the canvas cannot scroll up.

**Verified.** Foreground run: **205 passed, 2 skipped, 0 failed**, 3.6
minutes. HW011 held at `f4a857da…` before and after.

## Decision made in bullet two

Regions draw at their **true** length, and the handle is the affordance —
chunky, outside the region's extent. A 1 s region is 10 px of sound with two
big handles, not 44 px of fiction. This resolves the padding question the
critic raised.

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
