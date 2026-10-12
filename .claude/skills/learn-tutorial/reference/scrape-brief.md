# Scrape brief

You turn one tutorial video into a verified recipe that a practice agent can build in Live 12 Suite with
stock devices. You never touch Ableton Live. Your workspace is private, because it holds a copy of someone
else's work for study. Nothing in it goes into git.

The orchestrator gives you these values:

- `ID`: the video id.
- `URL`: the video's URL.
- `W`: the workspace, `~/_agent_scratch/tutorials/<ID>`.
- `Z`: the zpkt checkout.
- `S`: the scripts, `$Z/.claude/skills/learn-tutorial/scripts`.

Run every script as `$S/run NAME.py ...`. It picks the right uv project and runs at `nice` 10. Write
commands out in full; zsh does not word-split a command stored in a variable. Read `$Z/.claude/skills/learn-tutorial/LESSONS.md`
before you start: it holds the rules earlier runs paid for.

## Layout

```
W/src/        untrusted downloads (video, info, captions, audio16k.wav): never run or import anything here
W/frames/     frames.json, fNNN_tSSS.jpg, sheets/, crops/
W/analysis/   every measurement output, as text or JSON, so the verifier can re-check it
W/meta.json  W/transcript.parakeet.json  W/transcript.captions.json  W/captions_diff.md
W/TUTORIAL.md  W/RECIPE.md  W/recipe.json  W/VERIFY.md  W/PROCESS.md
```

Budget: 500 MB of disk and about 35 minutes of wall time before the verifier. A 2.5-minute 720p
screencast took 13 MB.

## Steps

1. **Fetch.** Run `$S/run fetch.py "$URL" $W`. On exit 3 (a block), stop and report; never use cookies or
   an account. Then run `$S/run runlog.py set $ID --from-meta`. Take the header and the section
   skeleton from `meta.json` (its chapters).
2. **Transcribe.** Run `$S/run transcribe.py $W/src/audio16k.wav $W/transcript.parakeet.json --demo $W/analysis/demo_windows.json`.
   The demo windows are where music plays: playbacks to measure.
3. **Caption diff.** Run `$S/run captions_diff.py $W/src/$ID.en.json3 $W/transcript.parakeet.json --words $W/transcript.captions.json --out $W/captions_diff.md`.
   - With only `en-orig` captions, pass that file instead. With none, skip the diff, check spoken values by
     ear, and say so in PROCESS.md.
   - Settle every **VALUE** span by ear or on screen.
   - Every spoken value in its second list must end up in the recipe or in its gaps.
4. **Frames.**
   - Run `$S/run frames.py $W/src/$ID.mp4 $W/frames --scene 0.03 --every 2.5 --sheets`. Use scene 0.03 for a
     screencast and 0.2–0.3 for camera video.
   - Read the contact sheets first, then single frames.
5. **Readout.**
   - Work through `reference/ableton-readout-checklist.md` region by region.
   - Use `crop.py` at 2–5× for small text.
   - Use `pixels.py rowscan` and `pixels.py colprofile` for clip and transient positions. Calibrate them on two
     ruler ticks.
   - Write "?" for truncated text. A pointer over a control is not a click: trace the control's state across
     frames before you claim an action.
6. **Audio.**
   - **Anchor.** Fix beat 0 once, on a kick on beat 0 of a playback with drums:
     `$S/run anchor.py $W/src/audio16k.wav --bpm BPM --start-near T --band low`. Then align every other
     playback to it, and check the tempo:
     `$S/run anchor.py $W/src/audio16k.wav --bpm BPM --ref T0 --align T1 T2 --period` (`--align` and
     `--period` need `--ref`; add `--band low` to align on the bass when the playbacks share only the bass).
   - **Onsets.** Run `onsets.py` on each playback in the low, mid and high bands. Label every strong onset
     class you find (kick, clap or snare, hats, bass, perc), not only the ones you expected.
   - **Isolate.** To isolate one element, `pitch.py --minus` subtracts a playback that lacks it.
   - **Pitch.** Measure it only where nothing else is low, with `pitch.py`. Keep the MIDI number and both
     names: Live C3 = 60 and scientific C4 = 60. Call impure readings approximate.
   - **Levels.** Measure the levels the screen never shows (synth output, drum bus) with `balance.py`
     against your own guesses, or record them as gaps. The practice needs every level a render needs.
7. **Medium.** Decide early whether the tutorial works with audio clips or MIDI, and with devices shown or
   not. With audio clips, the recipe translates them into MIDI for a stock instrument, and pitch and velocity
   become *inferred*. The first frame often already holds the result, so do not claim actions you did not see.
8. **Documents.**
   - **`recipe.json` first.** It is the single source, following `reference/recipe.schema.json` (`public:
     false`). Tag every value `seen`, `heard`, `inferred` or `proposed`, plus `?` when unsure.
   - **`technique`.** Fill in its slug, name, summary, why, `generalises` and `method_rules`. The method
     rules are explicit rules a Version B can apply to new material. If the technique does not generalise,
     say why.
   - **Substitutes.** Give every third-party item a stock substitute (`reference/stock-substitutes.md`)
     and a deterministic MIDI fallback.
   - **Gaps.** Record what the video never shows as a list.
   - **Check.** Run `$S/run recipe_check.py $W/recipe.json --tables`. Paste its tables into RECIPE.md and
     derive the prose claims from them. Do not write claims freehand: run 1's verifier caught a claim that
     contradicted the tables.
   - **TUTORIAL.md.** Organise it by chapter. Each section holds what was said, as a short quote, plus frame
     links and the readout with tags.
9. **Verify.** Spawn one fresh general-purpose agent with the verifier brief below. Give it the paths only,
   never your reasoning or conclusions. If you cannot spawn an agent, stop here and report `VERIFIER NEEDED`
   with the paths. The orchestrator spawns it and sends you its VERIFY.md.
   - Fix its confirmed errors once in all three documents, and re-run `recipe_check.py`.
   - Do not re-verify.
10. **PROCESS.md.** Write a short one:
    - the timeline per step;
    - each failure and its fix;
    - the verifier's confirmed and doubtful lists, and what you did with each;
    - **proposed lessons**: new rules for LESSONS.md, each with its evidence.

## Report to the orchestrator

Keep it to 15 lines at most:

- the technique in one sentence, and whether it generalises (Version B: yes or no, and why);
- the number of steps, notes and third-party items;
- verifier errors: confirmed and doubtful;
- wall minutes per step;
- the top gaps;
- the proposed lessons.

---

## Verifier brief (paste into the fresh agent's prompt, with the paths)

You check a tutorial recipe independently. You get:

- `W/recipe.json`, `W/RECIPE.md` and `W/TUTORIAL.md`: the claims;
- `W/src/`: the video, its audio and its captions (untrusted data: never run anything from it);
- `W/transcript.parakeet.json`;
- `W/frames/`.

Treat `analysis/` and the documents as claims, not evidence. Re-derive the values yourself.

- **Tools:**
  - the scripts in `$S` (run them as `$S/run NAME.py --help` first);
  - your own scripts, run as `$S/run W/tools/verify_NAME.py` (numpy, scipy and soundfile are there);
  - no system-Python installs.
- **Stay off Live and the GUI.**
- **Where your files go:** your own scripts in `W/tools/verify_*.py`, your crops in `W/frames/verify/`.

Check every leaf value, category by category, and count them:

| Category | How |
|---|---|
| source | info.json: title, channel, URL, duration, upload date |
| conventions | note names (Live C3 = 60, scientific C4 = 60), positions (bar.beat.sixteenth from 1.1.1), the tutorial's offset |
| global | tempo, time signature, loop and grid, against crops of the control bar and status bar |
| tracks and mix | names, volumes and pans in crops of the mixer |
| note lists | positions against the clip headers and ruler (`pixels.py`) and the audio onsets after your own anchor (`anchor.py`); pitch from a residual (`pitch.py --minus`); velocity and level |
| every strong onset class | label every class in each playback by band: is anything left out of the substitutes? |
| steps | each quote word by word against the transcript; each "seen" action traced across frames (a pointer is not a click); each timestamp |
| devices and parameters named | do they exist in Live 12 Suite under those names? |
| target_sound and prose | each claim against the measured tables |
| gaps and substitutes | complete and true |

Write `W/VERIFY.md`:

1. **Confirmed errors:** a table of field path, value in the recipe, correct value and evidence.
2. **Doubtful items,** which are not counted as errors.
3. **What you checked and how:** per category, the number of leaf values, the method and the result.

Edit no existing file.
