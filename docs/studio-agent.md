# The studio agent, the checklist and The Wasteland (design)

A design, not yet built, written 14 October 2026 from Anthony's direction after the HW002 lab (`docs/lab.md`). The
lab's lesson is that its surfaces are good to touch and its sound was not to be trusted (`docs/sound.md`). This
design keeps the first and makes the agent, not a fixed page of 100 knobs, the way in.

## What it is a crystallization of

zpkt is already made by agentic production: Anthony talks to Claude Code, Claude renders options in Live, builds
sliders and pages for them, and Anthony listens and decides. The studio harness keeps just those capabilities
(talk, ask, render, play, decide, record) and drops the rest. That makes it safe, because the agent can only do what
the harness offers. It also leaves room for the affordances a terminal lacks: things to touch, things that are fun,
and a screen that helps him concentrate on one decision.

## The agent's three agendas

In order of priority:

1. **Do what Anthony says.** His request always comes first and is done the way he asked.
2. **Move the track through the checklist.** When he has not asked for anything, or a request is finished, the agent
   picks the next open item on the track's checklist and works on it. It renders options, asks a question, or
   offers a decision.
3. **The Wasteland.** Below both, the agent keeps material from Anthony's own library surfacing through the spine,
   in whatever way interests him (below).

## Tools the agent needs

- **Ask.** A question-and-answer tool: a question with choices (or open), which Anthony can answer now, later or not
  at all. The agent can come back to an open question, ask a follow-up, or ask again in another way. Questions are
  kept with the checklist item they belong to.
- **The checklist.** Read it, add items, change an item's status, attach evidence (renders, measurements, answers).
- **Render and present.** Changes go to Live through `hands`. What comes back is rendered audio, played by the
  player engine (`docs/sound.md`) and announced as studio already does (`present_music`).
- **Widgets.** Make a control surface for the question at hand, as a description the page draws (a widget kind,
  the parameters or macro it moves, the rendered stops it plays, the reference range on it). Not code. Widgets are
  cached, so a good one can be used again (see "From chat to a fixed flow").

## The checklist

One checklist per track. It covers the whole track across the spine (`docs/workflow.md`: collage, drums, arrange,
kick, mix, master, release), and each step drills down into sub-checklists from two sources:

- **The toolset**, with HW002 as the template: the set's devices and the moves the HW002 experiments made at each
  step (the scoop, COLDFIRE and the Decapitator, the hat staircase, the Short's cut, the batch 6 climbs).
- **The style**, from the references (`docs/hw002/references.md`): where the track sits against them on what each
  step can be measured on.

An item is one thing to settle. It has the step it belongs to; the question; what settled means; where it came from
(template, references, Anthony, the agent); its status (open, asked, being rendered, waiting for Anthony, settled,
skipped); and its evidence (renders, measurements, answers, the decision doc). Settled items roll up into the
step's percent through the workflow's records (`docs/inventory/records.toml`).

For HW002 today: collage, drums and arrange are done; the kick is being tightened before the mix. So its kick
sub-checklist is where the agent works. From the template, it holds the scoop, the distortion (batch 8.1's 37-50 %
target), the transient shaper, the kick bus EQ and compressor, and the rumble against the kick. From the references,
it holds deep sub (25-40 Hz, 7-9 dB under), the low end's mono (correlation 0.88 against 0.99-1.00), density
(crest), and knock in the mids.

### The checklist page

A separate admin view from the agent's chat. It shows the track's spine with each step's sub-checklist, every
item's status, open questions and evidence (playable through the player engine). The chat treats it like an
artifact: the agent refers to items by name, changes them, and the page shows what changed and who changed it.
Anthony can edit it directly too.

First draft (14 October 2026): `/studio/checklist/`, from `static/checklist/data/hw002.json`. The steps and their
items are HW002's for real; what is inside an item (sub-steps, the agent's question, a widget, evidence) is a
wireframe, labelled as mocked. It is meant to feel like a precise video game, so moving the track along is its own
pull: a current-objective HUD, the spine as seven gems, items that clear with a hold (the socket and the row fill;
on release a click, layered white rings and a diagonal flash across the step), a banner when a step is cleared, and
the next step taking over. Each step is a path: Anthony's move is its first open item (and any item waiting on his
listening), in amber; the agent works further down, so the items between are ready (cleared, each waiting on his
move above) on a dotted blue trail; the agent's own item is being cleared (a marching line and a scan); past it is
fog.
Checks are kept in the browser until the agent's store exists.

Second pass, from Anthony's feedback the same day:

- **No widgets in the checklist.** Tapping an item opens its sub-list (sub-items, mocked, that clear like items), and
  the work itself happens in studio: each item links to `/studio/?focus=<track>.<step>.<item>` (studio does not open
  on an item yet).
- **Switches for the plainest page.** Anthony preferred every tweak at its minimum, so three more switches and a
  "Simplest" button: a plain look (black and white, like a rendered markdown checklist, nothing moving), folding off
  (every step and sub-list open) and checking by a tap on the box. The game look stays one switch away.

### Release is never locked (14 October 2026)

Anthony can release at any time; the pre-release items shape and entice, they don't force. Gate items are decision
points, not doors; the current step is a suggestion; the agent's checklist agenda is to make the next item tempting,
not to unblock a sequence.

### Three concepts for a 2D, game-like checklist

Kept separate on purpose, each proving two features, each reading and writing the same checks
(`static/checklist/concepts/`, shared state in `model.js`):

- **Stamp rally** (`stamps.html`): a passport of seven stamp cards. A hold presses a stamp (a print that is the same
  for an item everywhere, from a hash), and what the agent has made ready shows as the ghost of the exact print.
- **Repair board** (`repair.html`): all 49 items as tiles on one screen. Scrub a decayed tile clean to restore it;
  opening an item again cracks the cleared items after it in its step, and a scrubbed crack heals in gold for good.
- **Crystal** (`crystal.html`): one crystal drawn as a pure function of the cleared items (same set, same SVG,
  whatever the order). Release now (mocked) freezes it as a pressing; later checks never change a pressing.
- **A tweaks panel** on a tab at the right edge changes how the page is built, live, kept in the browser: the current
  objective as a panel, a strip in the header (the default), a line in the header, the gems alone, or off; the gems;
  a tap opening the sub-list below or on a page of its own; a studio button on each row; the path line; the fog;
  clearing effects (full, subtle, off); the hold time; density; corner brackets.
- Every control acts on the touch itself (`onTap` in `tweaks.js`): iPhone WebKit can swallow the click after a touch
  when it thinks the page changed under the finger, and this page always animates.

## The reference space

The references are the base of every flow. Each reference, measured on a step's dimensions, is a point; together they
mark out a space of possibilities. The harness's job is to make it easy to play in a bounded region around that
space, while about 10 % of what it offers deliberately breaks out of the region on one or more dimensions.

- **A control is laid out in reference terms.** Most of its travel spans the safe region, with each reference marked
  on it, and the ends are a marked edge zone beyond it. A page of choices draws about one in ten of them from the
  edge.
- **Four references are few.** In five or more dimensions they cannot outline a shape, so the region is a range per
  dimension (their spread plus a margin) until there are more references.
- **The references are finished mixes,** so a step's dimensions must be measurable on a full mix: the kick's are
  things like sub weight, decay between hits, crest, click energy and low-end correlation, not anything that needs
  the kick on its own. Those limits shape what each step's decisions can be about.
- **Macros are defined in this space.** "Mid warmth" or "sub weight" moves the track along one measured dimension;
  which knobs do that, and how far, is learned from rendered sweeps, measured with `ears`.
- **The region decides what to render**, since the player engine can only play what exists (`docs/sound.md`).

## From chat to a fixed flow

The interface runs on a line between two ends:

- **Fluid.** A chat input. The agent answers with widgets made for the question, which are cached.
- **Fixed.** At the extreme, a sequence of pages, each one decision on one input, often a macro over several
  parameters, so the decision is a high-level idea ("mid warmth") rather than a knob.

The design space is between them. What is fixed in advance (the question, the dimension, the widget, the range)
varies along the line; what never varies is that every control is bound to the reference region plus its edge.
Widgets move along the line by use: a chat widget Anthony returns to is kept, then given a page, and pages in order
become a step's fixed flow. The next track's kick step then starts with HW002's best widgets.

## The Wasteland

Like an open world game (Crimson Desert), there should always be things beneath the surface to find. The agent's
third agenda keeps Anthony's personal music library flowing through the spine in whatever way interests him:

- **Raw**: sounds and stems from the library, to look through and listen to.
- **Collaged**: pieces of them laid out together.
- **Processed and mashed up**: resampled, chained, crossed with each other.
- **Made whole cloth**: background agents making techno from scratch, as experiments.
- **Learned**: background agents gathering production ideas from the internet, and others training models such as
  RAVE (to make sound) and CLAP (to search sound by description).

Surfacing what interests him is the point: the agent learns what he stops to listen to and brings more of it. All
of it is heard through the player engine as rendered files, labelled with where they came from. His library audio
never goes into this repo, which is public.

## Open questions

- Which dimensions each step uses, and how each is measured on a full mix (the kick's first).
- The checklist's file format and where it lives (the repo for the template, the track's folder or the harness for
  a track's own list).
- How the agent chooses between its agendas mid-conversation, and how often the third one speaks up.
- Where The Wasteland's background agents run and what they may spend.
