# The workflow: seven steps from sound to Short

Anthony makes industrial hard techno Shorts for YouTube.
Every track goes through seven steps, in this order.
The order is the spine's lifecycle; ears and hands serve every step (see the README).

| | Step | What it means here | Done when |
|---|---|---|---|
| I | audio collage | Found and library sounds chosen, cut, resampled and laid out as the track's bed. Game audio, field recordings, voices, stems. | The bed exists on the timeline, with its resampled pieces. |
| II | drums | Kick, rumble, hats and percussion programmed. In this genre the rumble is part of the kit. | All four play across the arrangement. |
| III | arrange | The Short's shape: a 33–50 s cut with an arc, usually from a longer track. | A Short-length cut with three or more sections, and Anthony approves it. |
| IV | kick | The kick and rumble get their own chain: scoop, distortion, compression. It is its own step because the kick carries the genre. | The chain is built and Anthony has picked the sound. |
| V | mix | Groups and buses processed, levels and sends set, colour and space. | A mix render Anthony accepts. |
| VI | master | The master-bus chain and a mastered export for YouTube. | -14 to -11 LUFS integrated, true peak at most -1.5 dBTP, Short length. |
| VII | release | The final export goes up as a YouTube Short. | It is published and its link is recorded. |

Work happens out of order. HW002's mix batches ran before its Short was final.
So a track's headline is its **lowest incomplete step**.
That is the first step, in the order above, below 100 %.
A track at "III. arrange" may already have mix work done.

## Targets

- **Length.** 33–50 s, from Anthony's feedback on 1 October 2026 (see `docs/hw002/`).
  Genre Shorts that travel run 6–34 s.
  Label previews run 42–60 s per track (`docs/hw002/arrangement-references.md`). YouTube allows up to 3 minutes.
- **Grid.** Mostly 4- and 8-bar sections on a power-of-two grid. Never open on a single bar.
- **Loudness.** -14 to -11 LUFS integrated; YouTube turns louder masters down to about -14.
  True peak at most -1.5 dBTP, since AAC adds about 0.5 dB
  (`ears/mlab/guides/youtube-short-delivery.md`).

## What a tool can read

`hands library inventory` scores each step from the project folder. Every percent comes with
evidence lines that say where its points came from. The rules are points with caps:

| Step | Evidence in the project | Points | Cap |
|---|---|---|---|
| I | Audio clips on non-drum tracks: distinct files, resampled or consolidated files (`Samples/Processed`, `Samples/Recorded`), clips on the timeline. An audio-browser project of the same name. | 10 per file up to 50; any resampled file 20; 2.5 per clip up to 20; clips over 16+ bars 10. Browser: `stored` 10 + 2 per sound up to 30, `collage` 40 + 10 per region up to 80. | 100 |
| II | Track, group and rack-sample names: kick, rumble, hats, percussion. Drum clips on the timeline. | Kick 30, rumble 15, hats 25, perc 15; drums across 16+ bars 15 (session clips only 5). | 100 |
| III | The arrangement's length in seconds and its sections (runs of 4-bar blocks that play the same tracks, or named locators). The best of the project's sets, since a Short may be cut in its own set. | No clips 0 (session clips 10); a loop under 16 bars 20; fewer than 3 sections 35; under 25 s 40; over 64 s 60; 25–33 or 50–64 s 75; 33–50 s 90. | 90 |
| IV | A dedicated kick track or kick group, with the rumble; processing devices on it; automation on it; sets named for kick work. | Dedicated 20 (only in a shared rack 10); 10 per device up to 40; automation 10; kick-named sets 10. | 80 |
| V | Groups with processing, returns fed by sends, levels set (a Utility, a moved fader or automation), automation, a mix render. | 10 per group up to 30; sends 15; level share up to 20; 2 per envelope up to 10; a render 15. | 80 |
| VI | A limiter, clipper or bus compressor on Main; other processing on Main; a mastered export; its measured loudness. | Limiter 30; other 10; a master export 30; measured inside the target 20. | 80 |
| VII | A release candidate: "final", "release" or "youtube" in its name, or a video. Short length. | Candidate 30; Short length 30. | 60 |

**The caps are deliberate.** The heuristics see files, not sound.
A kick chain with six devices may still be the wrong kick.
So kick, mix and master stop at 80 %. Arrange stops at 90 %, release at 60 %.
The last stretch takes a record: Anthony's word, or a decision in zpkt docs.
Collage and drums can reach 100 % from the file. Their evidence is the material itself.

### Which set, which files

- **A project** is a folder directly under the library root that holds a `.als`.
  The track's name is the folder's, without Live's " Project" suffix.
  `Backup/`, `Samples/` and `Ableton Project Info/` are not searched for sets.
- **The set** is the newest by modification time. Sets named `debug…`, `ref…`, `test…` are skipped.
  Arrange alone looks at every set and takes the best.
- **Reference tracks are left out**: tracks named "ref", tracks in a "Ref" or "Trash" group, and a
  muted audio track that plays one long file through no devices.
- **Exports** are audio or video files that carry the track's name, a set's name or an export word
  (master, mix, final, bounce, render, demo). Files a set plays as samples are not exports.
  Extra folders (`--exports`, default the rig's `renders_dir`) count only files carrying the track's name.
  The name decides the kind: final, release, youtube or a video is a release candidate;
  master, limited or LUFS is a master; mix, premaster, bounce, stem, full or demo is a mix render.
- **Loudness** is measured only with `--measure`, only on master and release candidates, at most
  three per track, with `ears/mlab`'s calibrated meter.
- **Copies.** A set that plays samples from another project's folder gets a note: it is likely a copy.

## Records

A record sets a step's percent and beats the heuristic, in both directions.
The heuristic's own figure and evidence stay in the report beside it.
Records live in two places with the same fields:

- `docs/inventory/records.toml` in zpkt, tables keyed by track. Agents add records here in a PR.
- `zpkt-workflow.toml` in a project folder, with step tables at the top level.
  Anthony writes that one, so it wins. Agents never write into the library.

```toml
[HW002]
note = "The release is a YouTube Short cut from the full track."

[HW002.mix]
percent = 40
by = "docs"            # anthony: his word; docs: a decision in zpkt docs; agent: an agent's judgment
date = "2026-10-09"
note = "Batch 6 'all' is the baseline; batches 8.2-8.7 wait for listening."
source = "docs/hw002/batch-6-7-decisions.md"

[HW002.release]
percent = 100
by = "anthony"
url = "https://youtube.com/shorts/..."
```

The step keys are `collage`, `drums`, `arrange`, `kick`, `mix`, `master` and `release`.
An unknown key is an error, so a typo cannot hide a record.

A track can have a `status`. The only one is `canceled`: the track leaves the inventory and is listed under
"not scored" with its note (`[HW004]` / `status = "canceled"`; in a project file, `status` at the top level).
An unknown status is an error too.

## Running it

```bash
cd hands
uv run hands library inventory                       # the rig's library_dir; a table
uv run hands library inventory --markdown            # a table and each track's evidence
uv run hands library inventory --json                # lib/contracts/inventory.schema.json
uv run hands library inventory --root DIR --root DIR2 --exports DIR3 --measure
```

The library root comes from the rig settings: `library_dir` in `~/.config/zpkt/rig.toml`, or
`ZPKT_LIBRARY_DIR` (see `hands/README.md`). The scan is read-only.
It lists folders and reads `.als` files.
With `--measure` it decodes at most three files per track.
Reports are dated in `docs/inventory/`.

## Known weak spots

- **Names carry the drums.** A kick track called "Audio 3" is not found unless its samples say kick.
- **The newest set may not be the furthest.** A scratch set saved last would be scored instead.
- **Export names are guesses.** "short" is not a release word: HW002's experiments use it for short splashes.
- **Work outside the library is invisible.** HW002's Short cuts and mix batches live in copies.
  Records carry them.
- **Points are not taste.** Two groups with EQ score the same, good mix or bad.
