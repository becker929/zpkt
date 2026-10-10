---
name: ab-1bar
description: Make an A/B that switches between two versions every bar, loudness-matched, and present it in Anthony's studio chat. Renders missing versions in Live in one pass together with the likely next asks ("more", "the other end"), so those play within a second. Use whenever Anthony should compare a change against the current sound by ear, and for "more", "less", "go back", "the other way".
---

# ab-1bar

```bash
cd hands && uv run --extra plans hands plan ab A B        # A, B: plans (skill render-plan), inline JSON or files
```

It renders whatever of A and B is not cached, plus the write-ahead guesses in the same Live pass:

- **more**: B pushed as far again from A (B + (B - A)), clamped to each knob's range;
- **the other end**: A pushed the other way (A - (B - A)).

Then it cuts one file: both versions at -14 LUFS (same loudness, so louder never wins by itself), the first bar
dropped (the previous pattern's tail), bars alternating A, B, A, B with 10 ms crossfades. It prints:

```json
{"path": ".../ab/<keyA>-<keyB>-A1.flac", "title": "drive 40% vs drive 50%",
 "ab": {"bar_seconds": 1.5, "bars": 7, "first": "A", "every": 1, "a": "drive 40%", "b": "drive 50%"},
 "rendered": 4, "cached": 0, "seconds": 24.1,
 "ahead": [{"label": "more: drive 50%", "plan": {...}}, {"label": "the other end: drive 40%", "plan": {...}}]}
```

Then call `mcp__studio__present_music` with `path`, `title` and `ab` exactly as printed (and a one-line `note`
on what to listen for). The phone lights A or B in time.

## The loop

- "More" / "further": `hands plan ab B MORE` where MORE is `ahead[0].plan` from the last output. It is cached, so
  the A/B is ready at once (and renders the next guesses).
- "The other way" / "go back further": use `ahead[1].plan` against A.
- "Play it again" / "loop it three times": `mcp__studio__play_music`, no render.
- Options: `--first B` to start with the new version, `--every 2` to switch every 2 bars, `--no-write-ahead` when
  nothing more is likely to be asked.
- Tell Anthony the difference in plain words and numbers ("B has the drive at 50 percent, A at 40"). Keep labels
  short: they are spoken.
