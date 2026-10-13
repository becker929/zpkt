---
name: options-slider
description: Bake a handful of options in Live (one knob at N values, N steps between two plans, or any plans) into one file and present it in Anthony's studio chat as a slider or buttons. His phone keeps every option in memory and switches between them itself, on the beat, with no round trip to the Mac. Use when he wants to try a range ("give me a slider for the kick drive", "somewhere between these two", "show me a few reverbs") rather than one A/B.
---

# options-slider

The options are baked once, in Live, through the plan cache (skill render-plan): packed P to a Live pass, so a
16-stop slider on a 16-pattern kit is one load and one export (about 40 s), and options rendered before cost
nothing. Then his phone has all of them. Moving the slider or tapping a button switches at the same place in the
bar, on the phone's own clock. Only these options exist; anything in between is a new bake.

```bash
cd hands
uv run --extra plans hands plan slider KIT KNOB [--from LO --to HI] [--stops N] [--scale log] [--base PLAN]
uv run --extra plans hands plan line A B [--stops N]            # every knob moving together from A to B
uv run --extra plans hands plan options PLAN PLAN ... --name "reverb on the clap" [--now K]
```

- `slider`: one knob at N evenly spaced values (default: its whole range, one Live pass of 8 to 16 stops). `--scale
  log` for frequencies and times. `--base PLAN` holds other knobs at a plan's values (what he kept before).
- `line`: N plans from A to B. A good second step after an A/B: "somewhere between".
- `options`: any plans on one kit, shown as buttons with each plan's label. `--now K` marks the one that sounds like
  the set now.
- `--bars` (default 4) is bars per option. The file stays under 135 s, because his phone keeps it decoded, so many
  options get fewer bars.

It prints:

```json
{"path": ".../options/<hash>.wav", "title": "rumble Drive",
 "options": {"layout": "slider", "name": "rumble Drive", "bar_seconds": 1.98, "bars": 4, "now": 4,
             "options": [{"label": "0%", "match_db": 3.1, "lufs": -17.1, "peak_db": -4.2}, ...]},
 "plans": [{"label": "0%", "key": "...", "plan": {...}}, ...], "rendered": 16, "cached": 0, "seconds": 41.0}
```

Then call `mcp__studio__present_music` with `path`, a short spoken `title`, `options` exactly as printed, and a
`note`: one or two short spoken sentences on what the options are and what to listen for ("Nine drive settings on
the rumble, clean to crushed, one bar each. Listen for when the kick starts to break up."). With autoplay on it does
not play at once: after your reply, the app says the title and the note, counts in ("Three, two, one."), and sweeps
through the options once on his phone, one bar each, low to high. So your reply needs only a few words ("Here's the
drive slider."); don't describe the slider again. After that he plays and moves the slider himself. They play
level-matched by default (`match_db`), so louder never wins by itself; the card's Match loudness toggle turns that
off to hear Live's own levels. If loudness is the point (a volume or a gain), tell him to turn it off.

## What he sends back

The card's buttons send his next turn as text:

- "Keep rumble Drive at 62%: option 6 of 9 on card 41." Use that option's `plan` from `plans` (match by label) as
  the new base. Say what it is in plain words. If he wants it in the song, that is a separate, checked Live step.
- "Finer on rumble Drive between 50% and 75%, around 62% (card 41)." Bake again with `--from`/`--to` at those two
  options' values (from `plans`), with the same `--base`.

Keep labels short: the card shows them large, and you may say them.
