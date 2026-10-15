# The map, the artist agent and the gallery (design)

A design, not yet built, written 14 October 2026 from Anthony's direction after the map round
(`docs/studio-agent.md`, "The map round"). It covers three things: what the map is as a game, an agent whose job
is to make the app more rewarding over time, and a gallery that keeps everything it makes.

## The map as a game

"Do a thing, reveal a place" runs through a long chain of games, and each link adds a relationship between the
player and the map:

- **Reveal**: fog of war, Metroid's map rooms. The map records where you have been.
- **Access**: Zelda's overworld, Hollow Knight's map seller. What you did opens the way to somewhere new.
- **Knowledge**: Outer Wilds, Tunic's manual pages. What you understood changes what the map means.
- **Building**: Death Stranding's roads, Stardew's community centre. The map shows what you put into it, and it
  can decay and be repaired.
- **Life**: Pokémon Go, Animal Crossing. Other things move about on the map, and it changes with time and season.
- **Collection**: Animal Crossing's museum. What you found is kept and displayed.

Here the actions are music production tasks: a checked item reveals its room and its find, a cleared step opens a
zone of The Wasteland. Release is never locked (`docs/studio-agent.md`): the map entices and never forces.

**The rule the crystal taught: the map is drawn from the work.** Its details come from what was actually decided,
deterministically, not from a random roll. Settling the drive at 41 % gives that room a particular roughness;
the mid-warmth dial sets the colour of its lamp; the reference zone a measure landed in shapes the ground. A
detail that is true of the work is worth more than a pretty one, because it is a record of the work. The map is
the track's illuminated manuscript: the text is the work, the illumination grows around it.

## The artist agent

An agent whose job is to make the app more rewarding to use, in response to Anthony's actions and feedback. This
is a learning problem: it learns what delights him and what he tires of, and how that changes over time.

### Feedback: thumbs on every view

- **Two buttons on every view**, a thumbs up and a thumbs down, on opposite edges of the screen, always available
  and never in the way of the work.
- **A press is stored at once** (before anything else happens), with what was on screen and what had just
  played: the view, the work of art showing or just finished, the item and track, the time, and how long into
  the session.
- **Then a quick question.** The agent may follow up in a small pop-over chat ("the shake, or the sound?"). It
  can be answered, or dismissed. The press counts either way.
- The same pop-over is how the agent asks anything, on any view (the studio agent's ask tool,
  `docs/studio-agent.md`).

The other signals are what he does: commits made after a reward against before it, how long he stays on the
splash, whether he opens a find, what he skips.

### What it makes: works, not code

A **work** is one piece of juice: what happens when something is done. It is a description the page performs, as
widgets are (`docs/studio-agent.md`): which primitives, in what order, with what values, bound to which facts of
the work. Primitives are the page's vocabulary: camera moves, particles, stamps and seals, map features (lamps,
weather, figures on trails, constellations), type and illumination, sounds. New primitives are added as code
through reviewed PRs; the agent composes and tunes them.

Sounds are rendered in Live, never made in the browser (`docs/sound.md`). The check sounds' recipe
(`hands/scripts/ui_sounds/`) is the pattern: the agent writes a variant and Live renders it.

### How it learns

- **Like the reference space** (`docs/studio-agent.md`): most of what it offers comes from the region of what he
  has liked, and about one in ten deliberately goes outside it. A delight is partly surprise, so a known-good
  work loses its effect when it repeats.
- **Novelty wears off.** A work's value falls with how often he has seen it. The agent rotates works and keeps
  rare ones rare.
- **Rewards follow work only.** A reward comes after a real commit and never interrupts work. No streaks to keep,
  no countdowns, no loss for stopping.
- **Every work is versioned** with its parents, so a liked work can be varied and a disliked one traced to what
  changed.

## The gallery

Every reward is kept. When a commit plays a work, the gallery stores a **plate**: the work as it played, the map
at that moment, the item that was settled, and **the render of the task**, the audio Anthony approved. A plate is
a page of the manuscript: the decision, what it sounds like, and its illumination together.

- **Wings by track, rooms by step.** A wing's floor plan is that track's map.
- **Unlocks.** Works the artist has made but not yet awarded hang as silhouettes, so there is always something
  to come.
- **Listening.** A plate plays its render through the player engine. Walking a wing plays the track's decisions
  in order: how the track was made.
- **No end.** The gallery grows with every track.

Renders and plates live in R2 and on disk, never in git, as the check sounds do.

## Delights to start from

Each is drawn from the work or from his time with it, so it is true, not decoration.

1. **The room's lamp.** A settled room is lit in the colour of the decision: the warmth dial's position, the
   drive's heat.
2. **Rooms that play.** Tap a settled room to hear the render that settled it. The map becomes a place to listen.
3. **Worn paths.** Trails he walks often, to items he went back to, wear deeper.
4. **Weather from the session.** A late session brings stars over the map; a long one ends at dawn.
5. **The agents at work.** Small figures walk The Wasteland's trails while background agents run, and come back
   carrying finds.
6. **Marginalia.** Each settled row in the ledger gets a small drawing made from its decision, in the margin.
7. **Drop caps.** A step's numeral is illuminated as the step fills, finished when it clears.
8. **Anniversaries.** A week later a room glows once: "a week ago you settled the scoop".
9. **Constellations.** Finds taken into a track join into a constellation named after it.
10. **Rare seals.** Now and then the stamp is a wax seal with the date. Rare enough to notice.
11. **The key of the track.** The check sound is rendered in the track's key, so checking off HW002 sounds like
    HW002.
12. **Spectrum dust.** The particles take their colours from the measured spectrum of the approved render (drawn
    from numbers, not sound).
13. **Listen back.** Long-press the header map to hear every settled render in order.
14. **The last page.** At release the whole map folds up into a single manuscript page, the track's cover plate,
    hung at the gallery's door.
15. **A new track starts on blank vellum.** The first collage item is the first drop of ink.

## A first slice to build

1. Thumbs on every view, stored at once, with the quick-question pop-over.
2. Plates: each commit stores its work, the map, the item and its render; the gallery shows them by track and
   step, and plays them.
3. Works as descriptions: the current check and map juice rewritten as a few works over shared primitives, so the
   agent has something to vary.
4. The artist agent, offline at first: it reads the presses and answers, proposes the next variations, and the
   page rotates them in.

## Open questions

- Where the feedback and plates are stored (the harness's database, synced to R2 for renders).
- How the artist agent runs: on a schedule, after each session, or in the background with the other agents.
- How much it may change without asking: new works freely, new primitives only through reviewed PRs.
- What counts as the render of a task when the task has no audio (a decision, an upload).
