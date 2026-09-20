# 11 — Overnight handoff

Written while Anthony slept, 2026-09-19. Updated as each step lands. Short
sentences. Read top to bottom.

## HW011 has a collage in it now, and a new baseline hash

On the morning of 2026-09-20 Anthony used the view for real. HW011 holds three
regions across three tracks: a 34 s cut at the top of track 0, a 16 s cut on
track 1 stretched to about a third speed so it sounds for 49 s, and a 127 s cut
on track 2 starting near the fiftieth second.

Its hash is therefore **`5008266305d1d2ceb228b9b31eecf308e94dd24e02bc914713b569625047eee6`**,
not the `f4a857da…` that every brief written before this used. Use the new one.
The live guard behaved correctly throughout: the file moved before any run
started, not during one, so nothing fired and nothing should have.

The file is committed, so his collage is on the remote as well as on the disk.
The stakes went up with it: HW011 is no longer a sound set, it is work.

## Slices ship compressed now, and the win is a link, not a CPU

`GET /api/files/{hash}/slice` serves Opus at 96 kbps in an Ogg container.
HW011's fifteen first pieces went from **39,656,312 bytes to 1,861,122** — 21
times smaller on this material. Three of the fifteen come back at 3,572 bytes
because their first fifteen seconds are silent, which is what a sparse
collection does to an encoder.

**Where the time goes, measured in Chromium against the real stack.** Fetching
and decoding all fifteen first pieces is what a pass of the transport loop
pays. On loopback the change *costs* time: 164–196 ms before, 486–492 ms
after, because PCM needs no decoder and localhost has no bandwidth to save. On
a throttled link, which is the phone, it is the other way round: at 20 Mbit/s
16,645 ms before and 2,283 ms after; at 5 Mbit/s 64,754 ms before and 7,458 ms
after.

**The seam test's number did not move**: 143, 143 ms before and 155, 143 ms
after. That test answers the slice route from inside the test process, so what
it measures is the fixed cost of restarting a pass — a fetch, a decode and a
frame — and never a transfer. It is a good pin on the seam and a bad
instrument for this.

**The cache is 256 MB, beside the index in `audio-browser/slice-cache/`.** At
96 kbps that is about six hours of encoded sound: far more than any one
collage — HW011 is twenty-five minutes of material — and small beside the
15 MB index it sits next to, let alone the sources it is cut from. It holds
encoded copies of material that exists elsewhere, so the bound is chosen to be
generous and forgettable rather than tuned. Least-recently-used, keyed by
hash, start and end. The encode is 3.8 s for HW011's fifteen first pieces cold
and 0.09 s warm.

**The context is now asked for 48 kHz.** This machine's default
`AudioContext` runs at 44.1 kHz, and `decodeAudioData` was resampling every
slice into it: a 720,000-sample piece came back as 661,499 where the ratio
asks for 661,500. That is a sample of slop at every piece boundary and every
repeat, and it predates Opus. Asked for at 48 kHz, all fifteen decode exactly.

**Sample-exactness is checked on every decode, not only in a test.** The
server states the count in `X-Slice-Frames`; a decode that disagrees is said
in the bar rather than played. A browser that does not take the 48 kHz option
gets the ratio's rounding allowed, so the check cannot cry wolf.

## Read this first

The five gestures you sketched — stamp, trim, snip, stretch, hear it — are
built. Four are committed and reviewed; the fifth is green and under review as
this is written. Every bullet was built, verified by me in a foreground run,
attacked by an adversarial critic, fixed, and only then committed.

HW011 is untouched. Its hash is the same as when you went to sleep, and the
live tests now fingerprint every project file before and after they run and
fail the run if one moved. That guard exists because a throwaway probe wrote
an empty collage into your project early on; I restored it from git within
minutes, and then made it impossible rather than merely unlikely.

**Nine decisions are waiting for you**, listed under "Design questions" below.
None of them blocks using the view. They are places where I chose something
defensible and would rather you chose.

**What I would look at first, with your ears rather than my tests:** open
HW011 on the phone, stamp a few of its fifteen sounds, and play it. Everything
before this bullet was preparation for that moment, and no test I can write
tells you whether it sounds like anything.

## Status right now

Bullet one — choose a sound and stamp it — is reviewed and committed as
`aa6807a` on `feature/audio-browser`. Bullet two — trim — is reviewed and
committed as `3a1ae38`. Bullet three — snip — is reviewed and committed as
`0db8571`. Bullet four — stretch — is reviewed and committed as `d1e169b`.
Bullet five — hearing the whole collage — is reviewed and committed as
`1763b4c`. **The sequence you gave is complete.** All five are on
`feature/audio-browser` and pushed. Final state: 262 browser tests, 583 Python
tests, `mypy --strict` clean, HW011 unchanged.

## The worst bug of the night, and it was inaudible as a gap

The playback critic found it by measurement, not by listening. Pieces of a
region were scheduled at an accumulated moment and never checked against the
clock. Hold one chunk back fourteen seconds and a piece was told to start at
11.46 while the clock read 15.68 — and **Web Audio starts a past moment
immediately**. So a slow slice did not leave a gap, which is what I had
predicted in the brief. It made the region sound as two or three copies of
itself, all at once, and every quick piece after it fired together too.

On a phone over Tailscale, with fifteen regions fetching just in time, that is
a thing you would have heard as the piece "going wrong" with no way to say
why. Pieces are now clamped to the clock: a region that falls behind runs late,
stays one sound, and says `fell behind`.

Two more it broke and fixed: the scheduled-once rule did not hold during
`loading…`, so a region trimmed between the tap and the first sound played the
material the trim had removed; and nothing on screen said a region silenced by
an edit had gone quiet on purpose, which on a phone is hidden under the thumb
that did it.

## One test defect I found and fixed myself

The full suite failed once on `encumbrance.mock.spec.ts`, a test with nothing
to do with collage, and passed alone three times. Its `/api/board` route
handler outlives any one request; a board request still in flight when the page
moved on had its response disposed underneath the handler, which then threw and
failed a test that already had its answer. It now lets such a request go rather
than speaking for it. That flake predates tonight and would have kept surfacing
at random.

## Design questions, all of them, in one place

Nothing here blocks use. Each is a choice I made and would rather you made.

1. **Undo is session-only.** A reload clears it, so a deliberate held delete
   survives as a delete. Server-side history is the only real cure.
2. **A handle drags from its first pixel.** A five-pixel thumb slide while
   choosing an end trims half a second and costs an undo step. A tap slop
   would fix it and would break a deliberate four-pixel trim on a ten-pixel
   region, which another test pins.
3. **Trim and snip disagree at the start of a region.** The same forty pixels
   off the start gives trim `at_s` 5 and snip `at_s` 9: trim holds the box and
   changes what is heard at the top, snip holds the material's moment and
   moves the box down. Pinned by a test rather than argued about.
4. **One snip ends snip mode**, so each further snip costs a button tap.
5. **A stretch that shortens draws trim's strike-out stripes** over material
   nothing removes. Honest about extent, wrong about meaning.
6. **The two halves of a snip share a name and a hue.** Only position and
   waveform tell them apart.
7. **The playhead does not scroll after itself.** On a thirty-six-minute piece
   the line is gone in about forty seconds. Following it would fight a thumb
   editing mid-play.
8. **An edit mid-play silences only the edited region**, and nothing on screen
   says that was on purpose.
9. **Varispeed, not pitch-preserving stretch.** I chose it for noise and
   texture and it is a contained swap if you want the other.
10. **A sound stamped mid-play is drawn and silent**, while a region *edited*
    mid-play stops. Change goes quiet, addition stays mute — an asymmetry
    that is defensible and was not chosen deliberately.
11. **Heavy overlap clips.** Fifteen voices at unity gain summed plainly. There
    is no way to fix it by ear until a balance gesture exists, which is the
    obvious next thing collage needs.
12. **Prefetch holds about 86 MB from the tap** — every region's first piece,
    including regions half an hour away that had half an hour to fetch.
13. **Auto-following the playhead.** A "tap to go to it" pill now appears when
    the line is off screen, which never moves the canvas by itself. Whether it
    should follow while you are not touching it is still yours.

## What I would build next, if it were mine to choose

**Balance.** It is the third verb in your own sketch — cut, move, balance — and
it is the only one missing. Fifteen voices at unity gain clip when they overlap,
so the piece cannot be judged by ear until levels exist, and judging by ear is
the entire point of the view. Everything else on this list can wait behind it.

The gesture that would fit what is already built: take a region up, enter a
balance mode by button as with snip and stretch, drag sideways across its box.
No number, no decibels, no fader — the region's fill gets lighter or darker so
loudness is something you see as weight rather than read. `gain` already exists
in the model, the player already applies it per voice, and the commit digest
already covers it.

## Bullet five — playing the collage — built, not yet reviewed

A transport in the bar, which is now two rows: the wide choose-or-mode target
across the top, and play, snip, stretch and undo sharing the width under it.
One row of five would have squeezed the filename to nothing on a phone.

`lib/collagePlayer.ts` is a conductor, not a second scheduler. It owns one
`AudioContext` and hands it to one `SlicePlayer` per region, so every voice
reaches one destination and Web Audio does the summing. Separate contexts
would mean separate clocks, which a collage cannot have, and iOS allows only
a handful of them anyway. `SlicePlayer` gained three things and lost nothing:
a shared context it will not close, a `startAt` moment, and a first piece it
can be handed instead of fetching.

**Only the first piece of each region is fetched before play starts.** The
spec says slices are fetched before play so nothing stalls mid-piece.
Fetching *every* second of HW011 would be about four hundred megabytes of WAV
before a note sounded, which no phone will hold. The first piece of fifteen
regions is bounded, and the rest arrive just in time the way a single region
already works. While the first pieces load the transport says `loading…`, and
a second tap gives up on them.

**Decisions I made, for you to overrule:**

- **An edit mid-play silences the region it edited, and only that one.** The
  piece is scheduled once, at the tap. Trim, snip, stretch or undo a sounding
  region and that region stops; everything else plays on; the change is heard
  on the next play. Rescheduling one voice into a mix already running would
  need a seam mid-sound, and stopping the whole piece would make the modes
  unusable while it plays, which the spec forbids.
- **A tap on a region while the piece plays only takes it up.** It does not
  play that region on its own. That is what keeps trim, snip and stretch
  reachable mid-play, since each of them begins by taking a region up.
- **Opening the picker stops the piece.** The picker is a sheet over the whole
  screen and its rows play. One thing sounds at a time.
- **The playhead exists only while something sounds.** It is not a lane
  waiting to be filled. At the end the piece stops itself and the line goes
  with it, so the canvas holds nothing but its regions again, and the next
  play starts at the top.

**What the tests measure rather than assert.** `listen()` in
`collage.mock.spec.ts` patches `AudioBufferSourceNode.start`, `.stop` and
`.connect` and records what the browser was actually told: the moment, the
buffer's length, the speed, the gain, the context's identity, and whether that
gain reached that context's destination. So "the mix sums" is checked as four
voices on one context all reaching one destination with overlapping sounding
intervals, not as the view agreeing with itself. Stop is measured too: every
voice silenced inside fifty milliseconds of the others.

**Not verified in Playwright.** WebKit under the iPhone descriptor did start
the context from a tap and the line moved at the right rate, so the gesture
path works. Real iOS Safari has rules a headless WebKit does not — the silent
switch, Low Power Mode, a backgrounded tab — and none of those can be
exercised here.

**What I did not fix.** The playhead does not scroll the canvas after itself.
On HW011, thirty-six minutes tall, the line leaves the screen in about forty
seconds and is not seen again. Following it would fight a thumb editing
mid-play, which is the thing this bullet had to keep working, so I left it and
am flagging it rather than deciding it.

**Verified by me.** Foreground run: **251 passed, 2 skipped, 0 failed**, 4.9
minutes; typecheck clean; HW011 held at `f4a857da…` before and after, with the
live guard reporting no real project file rewritten; ports 3101–3103 free
afterwards and nothing left running. One earlier full run had a single
`ECONNRESET` from the mock dev server in a bullet-four test; it passed on its
own and in the two runs either side of it.

## Bullet four's review found a bug that would have bitten your material

The bar announced a wall on nearly every stretch drag. The cause: whether a
drag had hit a bound was decided by comparing the *length* asked for against
the length that came back, but `rate` is rounded to six places before it is
stored, so those two differ by a fraction of the cut. Above about a two-second
cut that difference exceeds the threshold, and **on a cut of fifteen minutes —
HW011 has one — every probed position lied.** A drag alone on an empty track
was told there was no room on the track.

It now compares the rate asked for against the real walls, with a slack of
1e-9: a hair either side of a wall is arithmetic, not a wall. Also fixed: the
first moment of the canvas was reported as a crowded track.

The critic also checked my own test change with arithmetic rather than
opinion — the constant offset cancels exactly, so the measurement equals
`translateY`, and the clamp stays independently pinned by the stored rate and
the box height. It did not hide anything.

**Two more design questions for you.** A handle drags from the first pixel, so
a five-pixel thumb slide while choosing an end trims half a second and costs an
undo step; a tap slop would fix it but would break the deliberate four-pixel
trim that another test pins on a ten-pixel region. And a stretch that shortens
a region draws trim's strike-out stripes over material that nothing removes —
honest about extent, wrong about meaning.

## Bullet four — stretch — built, finished by hand, under review

The builder died on a session limit partway through its own fixes. Of the four
it had found, three were already made; one test was still failing. I finished
it myself rather than resume a rate-limited agent.

**The failing test, and why its diagnosis was wrong.** It asserted the stretch
handle's absolute offset from the bottom of its box: expected 120, got 121. The
builder had called it "the box's 1-px border under the stripes" and was about
to chase the striped preview element. But the preview measured exactly 120 —
the extra pixel was in the *handle's resting position*, which sits one pixel
below the box because the box has a 1 px border. The behaviour was right all
along: `translateY` was exactly the clamped 120 the bound demands.

So the test was measuring a place when its claim was a distance. "The handle
stops at the wall" is a displacement, and measuring it absolutely dragged in a
border that has nothing to do with the bound. It now measures movement from
rest. I have told the critic to check specifically whether I weakened it,
because a friendlier measurement is exactly how a real defect would hide.

Verified by me after the change: **235 passed, 2 skipped, 0 failed** in the
foreground, HW011 unchanged, typecheck clean, ports clear, nothing left behind.

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

**The critic measured the delete instead of arguing about it.** Sweeping thumb
landings over the grab of a region alone on a track: a 40 px drag was a
whole-region delete on **44%** of landings for a 1 s cut, 33% at 2 s, 22% at
3 s — and a two-halves result on **0%** of drags of 20 px or more on anything
under 3 s. Short cuts are exactly what snip makes, and on them the amber band
sits under the thumb, so the warning was invisible where it mattered. Undo is
cleared on load, so a scroll-like sweep in snip mode was an unrecoverable
delete of a cut made by ear.

**Its fix, which I like:** a whole band must be **held still for 600 ms** to
arm. Amber fills over the hold; moving a tap's worth restarts it; a lift before
the hold removes nothing and leaves snip on with a hint to hold. The bar's
headline says what a lift will do. No modal, no new surface, undo unchanged.
Friction, not restriction, applied to a delete. Tests fail without it in both
the desktop and the phone spec, including a real sweep through a 10 px region
followed by a reload.

Also fixed: a drag that cut nothing silently switched snip off; undoing the
last region while snip was on left a stale mode label and hid the choose
button; regions lacked `-webkit-touch-callout: none`, so the 600 ms hold could
raise an iOS callout.

Verified by me after the review: **223 passed, 2 skipped, 0 failed** in the
foreground, HW011 unchanged, typecheck clean, ports clear.

**Design questions for you, from the critic:** undo is session-only, so a
deliberate held delete survives reload as a delete — server-side history is
the only cure; one snip ends the mode, so each further snip costs a button
tap; and the start-snip / start-trim disagreement is now pinned by a test
("trim and snip disagree at the start"): the same 40 px off the start of
identical regions gives trim `at_s` 5 and snip `at_s` 9.

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
