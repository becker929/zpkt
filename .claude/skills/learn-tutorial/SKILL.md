---
name: learn-tutorial
description: Turn a music-production tutorial video into practised, rendered, filed knowledge. A scrape agent writes a verified recipe; a practice agent builds it in Live through hands (a version faithful to the tutorial, and the method on new material) and renders both; you send Anthony the MP3s, prepare the /skrng batch, file a technique card in docs/techniques/ and log the run so the next one goes better. Use when Anthony shares a tutorial link (YouTube), or asks to learn, study or practise a production technique from a video.
---

# learn-tutorial

You are the orchestrator. Two agents do the heavy work, and each ends with a fresh verifier of its own.
You handle the parts that are Anthony's or the rig's: Live incidents, delivery, filing and the retro. Every
run should leave the skill slightly better than it found it.

```
intake -> preflight -> scrape agent (+ verifier) -> practice agent (+ verifier) -> deliver -> file -> retro
```

## Rules

- **The workspace is private.** It lives in `~/_agent_scratch/tutorials/<id>/`: video, transcript,
  frames, quotes, the private recipe, renders. It stays out of git.
- **zpkt is a public repo.** Only our own words go into it: technique cards, the public recipe, LESSONS.md
  and runs.jsonl.
  - No transcript text, frames, crops, captions or media.
  - No quote over about five words.
  - Every card carries a credit line: the tutorial's title, channel and URL.
  - No rig details: host names, addresses, private folders, device names, Keychain items. No secrets
    (SECURITY.md).
  - Run `public_check.py` before every commit (step 7).
- **Live supervision rules.** Unchanged; Anthony set them.
  - One checked step at a time.
  - LOM calls well under 12 s.
  - Never discard or overwrite a set you don't own.
  - Read each dialog from a screenshot and press the non-destructive button.

  The practice brief repeats them, and `reference/recovery.md` covers every incident met so far.
- **Machine.** Run every script as `$S/run NAME.py`. It uses `nice` 10, the right uv project, and the main
  checkout's venvs when it runs from a worktree. Write every command out in full: zsh does not word-split a
  command held in a variable. Heavy work belongs to the agents, not to you. The disk is nearly full, so
  watch it (`preflight.py`).
- **Ask Anthony only for what is his:** taste, his sets, his system prompts, uploads. Otherwise act on the
  defaults here and report what you chose.

Variables used below:

- `Z`: your own zpkt worktree, made at intake. Never commit in a checkout other agents share.
- `S`: `$Z/.claude/skills/learn-tutorial/scripts`.
- `ID`: the video id.
- `W`: `~/_agent_scratch/tutorials/$ID`.
- `SET`: `tut_${ID}_practice`.

## 1. Intake

1. **Your own worktree.** `git -C ~/Desktop/zpkt fetch origin`, then
   `git -C ~/Desktop/zpkt worktree add ~/_agent_scratch/zpkt-learn-$ID -b learn/$ID origin/main`.
   That worktree is `Z`. Learn the id first from the URL (the `v=` or `youtu.be/` part).
2. **The workspace.** `$S/run runlog.py init "<url>"` creates `W/run.json`. It refuses with exit 3 when
   the id is already in `runs.jsonl` or `docs/techniques/README.md`. Then point Anthony to the card, and
   pass `--again` only if he wants a re-run.
3. **Look back.** Read `$Z/.claude/skills/learn-tutorial/LESSONS.md` and run `$S/run runlog.py compare`.
   Write what matters for this run into the agents' `Notes:` line (steps 3 and 4).
4. **Log stages.** `$S/run runlog.py stage $ID intake end`. Then log `stage $ID STAGE start` and `end`
   around every stage below.

## 2. Preflight

- **Scrape.** `$S/run preflight.py --stage scrape --json $W/preflight_scrape.json` checks the tools, the
  venvs, the disk and the onset self-test. The retro reads the self-test bias from this file.
- **Practice.** Run `$S/run preflight.py --stage practice --json $W/preflight_practice.json` before the
  practice. It is read-only on any set the run did not create, and checks:
  - whether Live answers, and its LOM latency;
  - dialogs, including unnamed ones;
  - the two dirty signals;
  - `Audio queue timeout` in Log.txt;
  - recent clients on the Remote Script;
  - system prompts that steal keys;
  - orphaned osascript;
  - Live's memory.
- **On a STOP,** read its `recovery.md` section and fix what is yours: restart Live, clear our own
  dialog, or kill our own orphan. Ask Anthony about his set or his prompts. Log each incident with
  `$S/run runlog.py incident $ID preflight KIND "..."`; the kinds are recovery.md's section names, or
  `other`.
- **A WARN for a system prompt.** LOM work can go ahead, but steps that type (save-as, render) refuse
  until the prompt is gone. Ask Anthony to answer his prompts before the practice reaches them.

## 3. Scrape

1. Spawn one general-purpose agent:

   > Read `$Z/.claude/skills/learn-tutorial/reference/scrape-brief.md` and follow it. ID=…, URL=…, W=…,
   > Z=…, S=… Notes: …

2. **If it reports `VERIFIER NEEDED`** (it could not spawn an agent), spawn the verifier yourself with the
   brief's verifier section. Then send its VERIFY.md path back to the agent (SendMessage).
3. When it is done, record:
   - `$S/run runlog.py stage $ID scrape end --verifier-errors N`, where N is the confirmed errors;
   - `$S/run runlog.py set $ID technique <slug>`, the slug from `W/recipe.json`'s `technique`.
4. **Same technique?** If `docs/techniques/` already has the slug, or the same technique under another
   name, this run compares instead of adding a card (step 6).
5. **Version A only?** If `technique.generalises` in `W/recipe.json` is false, the practice makes Version A
   only.

## 4. Practice

1. Run the practice preflight (step 2).
2. Spawn one general-purpose agent:

   > Read `$Z/.claude/skills/learn-tutorial/reference/practice-brief.md` and follow it. ID=…, W=…, Z=…,
   > S=…, SET=tut_…_practice Notes: …

   Handle a `VERIFIER NEEDED` report as in step 3.
3. **Stay available while it works in Live.** It stops and reports on surprises; it does not fix them
   alone. Handle the incident with `recovery.md`, log it, then tell it to continue (SendMessage). Never let
   it chain past a stop.
4. **When it reports,** record:
   - `$S/run runlog.py stage $ID practice end --verifier-errors N`;
   - `$S/run runlog.py metric $ID onset.render_max_ms X`, the worst planned-event error over the raw renders;
   - its incidents, with `runlog.py incident`.
5. **Check Live ended as it started.** `$S/run live_step.py pre --expect "<the set in front at preflight>"`,
   then `$S/run live_step.py edited`. Both only read. If the run started on an Untitled set, the saved `SET`
   may stay in front.

## 5. Deliver

1. **Send the MP3s.** Use SendUserFile, one message per version. Say what each plays and what to listen
   for, including the doubtful hits the report flags.
   - Without SendUserFile, print the MP3s' absolute paths and ask Anthony whether he wants them uploaded.
   - He is usually on his phone: print full URLs, never rely on `open`.
2. **Publish only when uploads are permitted.** Anthony's current upload policy is in
   `reference/publishing.md`.
   - While uploads are deferred, stop at "prepared, not uploaded". `W/practice/publish/entries.json` stays
     ready; record `$S/run runlog.py set $ID published prepared`.
   - When he permits uploads, follow publishing.md's Deliver section.

## 6. File the knowledge

1. **The card.** Write `$Z/docs/techniques/<slug>.md` from the private recipe and the practice report,
   in your own words. Copy the shape of `bass-from-perc-loop.md`: what it is and why it works, the steps with
   values, the stock substitutes, the measured results of A and B, and the credit line.
2. **The public recipe.** `$Z/docs/techniques/<slug>.recipe.json` with `"public": true`.
   - `why` fields are paraphrases. There are no `reason`, `heard` or evidence paths.
   - Add `results` from the measurements.
3. **The same technique, from another tutorial.**
   - Name the recipe `<slug>.<ID>.recipe.json`.
   - Add a "Compared with" section to the existing card: what differs, and what each render measured.
   - Add an index row for this tutorial.
4. **The index.** Add a row to `$Z/docs/techniques/README.md`.

## 7. Retro

The metrics are how this skill improves. Run `$S/run runlog.py retro $ID`. It writes or replaces this run's
line in `$Z/.claude/skills/learn-tutorial/runs.jsonl` and compares it with the earlier runs. Each
`REGRESSION` it prints asks for a change:

| Signal | Change |
|---|---|
| a stage took over 1.5× its median | find the slow step in PROCESS.md or PRACTICE-REPORT.md; script it, or cut it from the brief |
| verifier errors rose | turn the error class into a checklist line or a script check (`recipe_check.py`, `measure_render.py`) |
| the render onset error grew, or the self-test bias moved | fix the detector in `common.py` and add a case to `selftest.py` |
| an incident kind repeated | the recovery was not enough: add a preflight check, or move the fix into hands (TODO.md) |

Then:

1. **Update `LESSONS.md`.**
   - Add the reports' proposed lessons, each with the run id and its evidence.
   - Mark a lesson confirmed when it held again.
   - Revise or remove a lesson this run contradicted.
   - Keep the file short.
2. **Apply small changes now.** Make what the signals call for in the briefs, the scripts or this file.
   After any script change, run `$S/run selftest.py` and `uvx ruff@0.14.0 check $S`.
3. **Hands gaps.** Add new ones to `$Z/TODO.md` under "Hands gaps from learn-tutorial".
4. **Check what you will commit.** Run each of these from `$Z`; both must exit 0. A finding means you
   rephrase; `--allow` is only for quotes that are not the tutorial's (its title, Anthony's verdict).
   - `$S/run recipe_check.py docs/techniques/<recipe file> --public`
   - `$S/run public_check.py docs/techniques/<slug>.md docs/techniques/<recipe file> docs/techniques/README.md .claude/skills/learn-tutorial/LESSONS.md .claude/skills/learn-tutorial/runs.jsonl --transcript $W/transcript.parakeet.json --captions $W/src/$ID.en.json3 --allow "<tutorial title>" --deny ~/.config/zpkt/public-deny.txt`

   The deny list is private and optional: names that must never appear in zpkt. Briefs and scripts are not
   checked: they hold path templates, not tutorial text.
5. **Save.** Commit in `Z` on `learn/$ID`, push, open a PR and merge it (saving means merged). Then
   remove the worktree.
6. **Anthony's verdict.** It may come days later. Record it with
   `$S/run runlog.py verdict $ID "<his words>" --date YYYY-MM-DD`. Add it to the card, the index row and the
   public recipe's `results.verdict`, and save that change the same way. A verdict that rejects a version is
   a lesson.

## Files

| Path | What |
|---|---|
| `reference/scrape-brief.md`, `reference/practice-brief.md` | the agents' briefs, each with its verifier brief |
| `reference/ableton-readout-checklist.md` | what to read off a DAW screencast, region by region |
| `reference/stock-substitutes.md` | Live 12 Suite stand-ins per role, used and rejected |
| `reference/recipe.schema.json` | the recipe format, private and public |
| `reference/recovery.md` | every Live incident so far: detection and fix |
| `reference/publishing.md` | loudness, batch format, entries.json, uploads, the current upload policy |
| `scripts/` | `run` (the launcher) and the tools; each has `--help` |
| `LESSONS.md`, `runs.jsonl` | what earlier runs taught, and their metrics |
| `docs/techniques/` | the filed knowledge: the index, cards and public recipes |
