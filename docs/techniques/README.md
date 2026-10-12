# Techniques

These are production techniques learned from tutorials and practised in Live by the learn-tutorial skill
(`.claude/skills/learn-tutorial/`). Each card says, in our own words:

- what the technique is, and why it works;
- the steps, with values for Live 12 Suite's stock devices;
- what our renders measured;
- Anthony's verdict.

Each card has a recipe beside it (`<slug>.recipe.json`, in the format of
`.claude/skills/learn-tutorial/reference/recipe.schema.json`) that a practice agent can build again.

| Technique | Tutorial | Video id | Run | Versions | Verdict |
|---|---|---|---|---|---|
| [Bass line from a percussion loop](bass-from-perc-loop.md) | Finish More Music, "Ableton Bass Tutorial - Fast House & Techno Bass Patterns" | HztFoqevNMU | 1 (2026-10-11) | A faithful, B method on a stock loop | "sound really good" (2026-10-12) |

## How a card is written

- **Our own words only.** The tutorial's transcript, frames, captions and audio stay in the private run
  workspace (`~/_agent_scratch/tutorials/<id>/`).
- **Quotes** run to five words at most, and only when the exact wording matters.
- **Credit.** Every card opens with a credit line: the tutorial's title, channel and URL.
- **Tags.** Values are tagged in the recipe: seen, heard (paraphrased), inferred, proposed or measured.
- **Same technique, new tutorial.** It adds a "Compared with" section to the existing card, a recipe named
  `<slug>.<video id>.recipe.json` and its own index row, rather than a second card.
- **Check before committing.** `.claude/skills/learn-tutorial/scripts/recipe_check.py --public` and
  `public_check.py` in the same folder, against the run's transcript, must both pass.
