# Practice brief

You practise a verified recipe in Ableton Live 12 Suite through zpkt `hands`. You make two versions:

- **Version A** is faithful to the tutorial.
- **Version B** applies its method to new material, when `recipe.json` says the technique generalises.

You render both, measure them, and prepare them for publishing. You never upload anything.

The orchestrator gives you these values:

- `ID`: the video id.
- `W`: the workspace, `~/_agent_scratch/tutorials/<ID>`.
- `Z`: the zpkt checkout.
- `S`: the scripts, `$Z/.claude/skills/learn-tutorial/scripts`.
- `SET`: the set name, `tut_<ID>_practice`.

In the commands below, `W`, `S`, `SET` and `ALS` stand for their values. Write them out in full or as
shell variables you set in the same command: zsh does not word-split a command held in a variable.

Your inputs are `W/recipe.json`, `W/RECIPE.md`, `W/src/audio16k.wav` (the tutorial's audio, for levels) and
`$Z/.claude/skills/learn-tutorial/LESSONS.md`. Read the lessons first. Everything you make goes under `W/practice/`.

## Rules

These carry over unchanged. Anthony set them after a chained run left a prompt on his screen.

- **One checked step at a time.**
  - Before each Live step, check that no dialog is open, the expected set is in front and Live answers.
  - After it, read the result back.
  - On anything unexpected, stop and look. Never chain past a surprise.
  - `live_step.py` does the checks and logs every step to the file its `--log` names: always pass
    `--log W/practice/live_steps.jsonl`.
- **LOM calls stay well under 12 s.** The Remote Script gives up at 12 s while Live keeps running the code,
  and `live_step.py` stops the run after any call that took over 8 s.
  - Split big edits.
  - Never read a property in the call that wrote it.
  - Touch at most 20 parameters of one device per call.
  - Put `time.sleep(0.3)` between browser loads.
  - See `$Z/hands/skills/ableton-live-control/SKILL.md` and its `reference/lom-guide.md`.
- **Never discard or overwrite a set you don't own.**
  - The only set you edit or save is `SET`.
  - If the front set has unsaved changes and is not yours, stop and report. Do not save it, discard it or
    switch away from it.
- **Read each dialog from a screenshot and press the non-destructive button.**
  - Live's own alerts expose no text to accessibility.
  - Take the screenshot of Live's window first (on the rig, the private virtual-display skill says how)
    and read it.
  - Run `$S/run live_step.py dialog`. It lists the dialog's buttons with their positions and sizes; match
    them to the screenshot.
  - Press the non-destructive one (Cancel, or Don't Save on a throwaway) with
    `$S/run live_step.py --log W/practice/live_steps.jsonl press --index N --expect-pos X,Y`. It refuses if
    the button moved.
  - Never press Save over, Replace or Delete. Record the text.
  - `dialog` and `press` are new and untested on a real Live alert: on first use, report what they printed
    before pressing.
- **No offline DSP stands in for Live.** Every sound comes from a Live device. Offline code only measures.
- **Run things through the launcher.**
  - Every script: `$S/run NAME.py`.
  - The hands CLI: `$S/run --hands live ...`.
  - Your own helpers: `$S/run W/practice/tools/x.py` (numpy), or `$S/run --in hands W/practice/tools/x.py`.
  - Never `uv run --project` without `--no-sync`: it would build venvs on a nearly full disk.
- **No outer timeouts.** A timeout outside a GUI script leaves osascript running
  (`reference/recovery.md#orphaned-osascript`).
  - Run `render.py` with the Bash tool's `run_in_background`, or a 600000 ms timeout.
  - Give `live_step.py` `new`, `save-as`, `open` and `save` a 300000 ms timeout.
- **Typing.** Steps that type (`save-as`, `render.py`) refuse while a system prompt is open, because the
  keys could answer Anthony's prompt. Report that to the orchestrator and wait. Never answer the prompt
  yourself.

On any incident, follow `reference/recovery.md` and log it with
`$S/run runlog.py incident $ID practice KIND "what happened"`.

## Steps

1. **Preflight.** Run `$S/run preflight.py --stage practice --json W/practice/preflight.json`. It is
   read-only, and it confirms the orchestrator's check right before you build.
   - On a STOP, report it and stop.
   - Note the front set: you reopen it at the end.
2. **Plan.** Write `W/practice/PLAN.md`. It says what each render must contain and holds no results:
   - **Shape:** 2 bars of lead-in (not rendered), then sections that show the technique. Run 1 used 4 bars of
     source alone, 4 with the new part, then 8 with drums and the source removed.
   - **Every track:** its device, notes and fader.
   - **Every level a render needs:** source levels, not only faders. Set unseen levels with `balance.py`
     against `src/audio16k.wav`, and say which cells you fit.
   - **Delivery spec:** see `reference/publishing.md`.
   - **Render specs:** write one `W/practice/spec_A.json` (and `spec_B.json`) per version for
     `measure_render.py`. It lists the sections, the planned events per band, presence and absence, and the
     noise floors.
3. **Version B rules (if it generalises).**
   - Write `W/practice/plan_b.json` **before** you build:
     - the method as numbered rules;
     - the measured grid;
     - a decision for every grid position;
     - the onset bias from `selftest.py`.
   - **Screen the candidate material** with the method's own measure (`onsets.py --grid` on Live's render of
     each candidate) before choosing it. Run 1's first pick had no off-beat hits for the bass to answer.
   - Treat the arrangement context as part of the rules (a 4/4 kick takes the quarter notes).
   - Mark every rule you add after seeing a result.
4. **Set.**
   - Run `$S/run live_step.py --log W/practice/live_steps.jsonl new`. It refuses a dirty front set. It prints
     the set it replaced and that set's file, or uses a clean Untitled set that is already in front.
   - Then, at once, run
     `$S/run live_step.py --log W/practice/live_steps.jsonl save-as --dir W/practice --name SET`.
     Its set is `W/practice/SET Project/SET.als`; call that path `ALS`.
   - Never start from an old template: it cannot be saved in place (`recovery.md#old-template`).
5. **Build** in small checked steps. Each one is
   `$S/run live_step.py --log W/practice/live_steps.jsonl exec --expect SET @W/practice/snippets/STEP.py`,
   then a separate `... read --expect SET "result = ..."`.
   - **Tempo, time signature, loop.**
   - **Tracks and devices.** Load them from the browser. To reach a dB or ms target, bisect with the
     parameter's `str_for_value`. Live's display rounds, so aim for the lower edge.
   - **Clips.** Write them with `lom_clip.py` snippets, one 2-bar loop per track in session slot 0. Tile them
     into the arrangement by section with `duplicate_clip_to_arrangement`.
   - **Removal.** Take an element out by deactivating its clips (`clip.muted = True`), as the tutorial does.
   - **Save** after each milestone with
     `$S/run live_step.py --log W/practice/live_steps.jsonl save --expect SET --path "ALS"`.
   - **Probes.** Probe any device that might sound by itself (crackle, noise, an LFO source) with a short
     export that includes the lead-in (`recovery.md#device-self-noise`).
6. **Render.**
   - Run `$S/run render.py W/practice/renders/A_raw.wav --expect SET --start 8 --length 65 --log W/practice/live_steps.jsonl`
     in the background, adjusting the start and length to your plan.
   - Export into the same `renders/` folder every time (`recovery.md#export-folder`).
   - Switch between versions by muting the other version's tracks, and read the mutes back before rendering.
7. **Measure.**
   - Run `$S/run measure_render.py RENDER W/practice/spec_A.json --out W/practice/measurements/A_raw.json`.
   - Every check must pass. Planned events must land within 15 ms.
   - Fix the set, not the measure, then re-render.
8. **Publish prep.** Write `W/practice/publish.json` and run `$S/run publish_prep.py prep W/practice/publish.json --out W/practice/publish`
   (`reference/publishing.md`).
   - **Track notes:** say in plain words what each track plays and how it differs, and end with the credit
     line.
   - **Limiting:** if prep warns about heavy limiting, put Glue Compressor on Main and re-render rather than
     limit offline.
   - **Measure the MP3s** with the same specs plus a `delivery` block.
9. **Restore.**
   - Save `SET`.
   - Reopen the set that was in front at the start, with the file `new` printed:
     `$S/run live_step.py --log W/practice/live_steps.jsonl open --path "<that file>"`.
   - Read back that it is in front and clean (`$S/run live_step.py edited`), with the same track count and
     loop as before.
   - If the run started on an Untitled set, or `new` could not name the file, leave `SET` saved in front and
     say so in the report.
10. **Verify.** Spawn one fresh general-purpose agent with the verifier brief below. Give it the paths only.
    If you cannot spawn an agent, report `VERIFIER NEEDED` with the paths. The orchestrator spawns it and
    sends you its VERIFY.md.
    - Fix its confirmed issues once: re-render, re-measure and re-prep. Keep superseded files in `renders/superseded/`.
    - Do not re-verify.
11. **Report.** Write `W/practice/PRACTICE-REPORT.md` with these sections:
    1. what was built (tracks, arrangement, renders, files);
    2. recipe steps (each step's status, time and the hands/LOM calls used);
    3. measured results for A and B (raw and MP3);
    4. how faithful A is (exact, substituted, restructured, not reproduced);
    5. Version B's choices and why (rules, grid, doubtful hits);
    6. friction and hands gaps;
    7. recommendations, including proposed lessons;
    8. the verifier (its passes, confirmed issues and fixes).

## Report to the orchestrator

Keep it to 15 lines at most:

- the MP3 paths and `W/practice/publish/entries.json`;
- per version: the bass (or main) onset max error, sections LUFS, MP3 LUFS and true peak;
- verifier issues: confirmed and fixed;
- incidents by kind;
- Live's state at the end: the front set and whether it is clean;
- the doubtful points Anthony should listen for;
- proposed lessons.

---

## Verifier brief (paste into the fresh agent's prompt, with the paths)

You check practice renders independently. You get:

- `W/practice/PLAN.md` and the specs;
- `W/recipe.json` and `W/practice/plan_b.json`;
- the raw renders in `W/practice/renders/`;
- the MP3s in `W/practice/publish/`;
- the set at `W/practice/<SET> Project/<SET>.als`, which is gzip XML: read it offline.

Do **not** read `measurements/`, `tools/`, `live_steps.jsonl` or the report. Measure everything with your own
code: write it in `W/practice/verify_tools/` and run it as `$S/run W/practice/verify_tools/NAME.py` (numpy,
scipy and soundfile are there). You may use `$S` scripts, but
re-implement the method of Version B yourself from the text of `plan_b.json`; that is how run 1 caught a
21 ms timing bug. Never touch Live.

Check:

1. **Shape per section.** Each element is present or absent as planned: template projection, band levels
   and blind onset counts.
2. **Event timing.** Within 15 ms. Count extra and missing events.
3. **Pitches** against the plan, in Hz and MIDI.
4. **Version A** against the recipe's note lists, track by track.
5. **Version B.**
   - Does each event obey its own stated rules on correctly timed measurements?
   - Are the labels in `plan_b.json` true (the loop name, the offsets)?
6. **Delivery.**
   - **Loudness:** MP3 LUFS and true peak against the spec, and the spread between versions.
   - **Format:** CBR bitrate and sample rate.
   - **Integrity:** no clipping, no silent stretches, durations as planned, each MP3 its own version (lag and
     residual against its raw).
7. **The set**, read offline: the devices, notes and faders match the plan.

Write `W/practice/VERIFY.md`:

- a verdict;
- a table of checks with pass, fail or doubtful and the measured values;
- the confirmed issues;
- the doubtful items.

Edit no existing file.
