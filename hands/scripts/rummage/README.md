# SH001, the short The Rummage plays

The music for The Rummage (`docs/rummage.md`): a 32-bar short in three parts with three options each, made in Ableton
Live 12 Suite by hands and rendered as all 27 combinations. The page plays the renders (`docs/sound.md`); it never
makes or changes sound.

- **118 BPM, 4/4, 32 bars, 65.085 s. D minor, dorian colour.** Two bars a chord: Dm9, G9, Bbmaj7, A7sus4 to A7, three
  times; the last time round turns home: Dm9, G9, Bbmaj7, D(add9).
- **Arrangement:** bars 1-8 the bed alone, swelling in over four bars (in its velocities: the LOM cannot write
  automation into arrangement clips); 9-16 drums come in (kick and hats, then the whole kit, a fill at 16); 17-28 the
  bass and the full groove (extra percussion, fills at 24 and 28); 29-32 the outro (one last hit, the bass holds Bb
  then D, the bed rings out). A shared track, `seams`, plays in every combo: Core Library found sounds on a Drum Rack
  (a cassette going in at bar 1, a radio tuning in over bars 7-8, a noise riser and a broken box into bar 17, a drop
  and vinyl run-out crackle at 29). Every part is humanized a little (seeded, so a rebuild is identical).
- **The options** (`parts.py`; names and lines for the page are in `OPTIONS`):

| Part | 1 | 2 | 3 |
|---|---|---|---|
| bed | Music box & hiss: Music Box (the tune over an eighth-note arpeggio), Chorus-Ensemble; a looping tape-noise sample | Parlour upright: Childhood Home Piano in a lopsided comp; Toy Piano Bells on the tune through a chorus | Branches & tin bowl: Tree Branches pad holding the chords; Tin Bowl on the tune at half speed |
| drums | Tin-can break: Rattle Kit, a broken beat | Clockwork four: Clockwork Kit, four on the floor, a ticking off-beat | Cutlery shuffle: Perc Kitchen Kit (spoons, knives, pans, glass) in triplets, a Kick Wood sample on pad 35 |
| bass | Round sub: Sub Mellow through Saturator's Bass Shaper | Rubber band: Tension Rubber Bass, plucked sixteenths | Bowed gut: Cat Gut Bass through a hard-curve Saturator |

  Everything is Live's own Core Library (the Lost and Found pack is not installed on this Mac): presets, three of its
  kits and two of its samples. No purchased audio, nothing from Anthony's library.
- **For a phone** (round 3): bass 1 and 3 also send to return C, C-Phone (Saturator, hard curve, into EQ Eight
  keeping 220 Hz-2.5 kHz), their harmonics where a phone speaker has them; `make.py build phone` sets it up.
- **Main:** EQ Eight (high-pass 32 Hz), Glue Compressor (2:1 at -12 dB, 10 ms, auto release), Limiter (True Peak,
  ceiling -1.8 dB). The 27 land at -14.5 to -14.1 LUFS; the page's `gain_db` matches them to -14.

```bash
cd hands
# in Live: File > New Live Set (Live's default: MIDI tracks, Reverb and Delay returns), then
uv run python scripts/rummage/make.py save            # Save As SH001_rummage into ~/_agent_scratch/rummage/set/
uv run python scripts/rummage/make.py build           # tracks, instruments, notes, mix, master (each step checked)
uv run python scripts/rummage/make.py save
uv run python scripts/rummage/make.py stems           # each option alone through Main (for the balance), 9 exports
uv run python scripts/rummage/make.py render all      # the 27 combos, ~18 s each
uv run python scripts/rummage/make.py measure         # length, peak, true peak, LUFS
uv run python scripts/rummage/make.py encode          # AAC 192k .m4a, checked, added beside older ones + audio.json
```

`build` takes steps too (`build notes`, `build notes:upright` for one track, `build mix master`), and `combo 1-2-3`
sets the mutes for one combo. A combo un-mutes exactly its three options' tracks; everything else in the set is the
same for all 27, so they line up sample for sample.

**The region's interface sounds** (`sounds.py`, its own set `SH001_ui`): paper, tin, wood, brass and found objects,
in D where pitched, with their energy where a phone speaker has it (150 Hz to 6 kHz: Main high-passes at 130 Hz and
shelves off above 8 kHz), peaks at -3.5 dBFS or lower. Each sound has a 6-second slot, so one export renders them
all; `cut` slices, trims (where it stays under -60 dBFS), fades the last 20 ms and checks; `encode` adds
`ui-<name>-<hash8>.m4a` to the audio folder and writes `static/checklist/rummage/sounds.json` (a list per name: step
has three). The page plays them through `rummage/sounds.js`, as rendered.

| Sound | What it is | Length, peak |
|---|---|---|
| step (3) | a slice of paper rustle, a few semitones down, over a muffled wooden knock (felt) | 0.18-0.24 s, -14 to -16 dBFS |
| pickup | a paper whoosh rising in pitch; a music box A5-D6 and a soft tin bell land 30 ms in | 1.9 s, -9.4 |
| place | a resonant wood knock, an Operator thump on D3, a tin bell on D5 and A4 | 2.5 s, -9.8 |
| open | a door lock's jiggle and latch clunk (at 0.36 s), a heavy door's body, a spring | 1.05 s, -6.6 |
| lever | six ratchet teeth in 90 ms into the slam at 100 ms (door, metal impact, D2 thump), tin rattle, a bell on D4-A4 | 2.9 s, -3.6 |
| finish | a needle drop, the groove's crackle, a warm pad swelling on D-A-D-E, a music box sparkle at the top | 2.9 s, -5.3 |
| tear | paper ripping (a rustle pitched up as it goes, fibres scraping), parting with a snap | 1.1 s, -3.6 |
| tick | a small wooden detent, for the selector | 0.15 s, -14.4 |
| stamp | a box slap, a D3 thump and a knock: the artifact's stamp | 0.39 s, -3.6 |

```bash
uv run python scripts/rummage/sounds.py new       # File > New Live Set, saved as SH001_ui (save the front set first)
uv run python scripts/rummage/sounds.py build     # 7 tracks: a Drum Rack of samples, two paper Simplers, music box,
                                                  # tin bell, pad, Operator; the notes; Main
uv run python scripts/rummage/sounds.py render && uv run python scripts/rummage/sounds.py cut
uv run python scripts/rummage/sounds.py encode
```

Notes: a Drum Rack pad's Simpler shows only 33 parameters (no filter, no pitch-envelope amount), so the whoosh and
the rip are Simplers of their own. Paper LDre is quiet (about -35 dBFS): the rip needs +15 dB (a Utility), the whoosh
+20. Live's 24-bit export dithers, so each render's files get new hashes even when nothing changed.

Where things go: the set and the WAV renders under `~/_agent_scratch/rummage/` (never `~/Music`), the .m4a files in
`~/_agent_scratch/studio/regions/rummage/audio/` (the harness serves them at `/studio/regions/rummage/audio/<file>`),
the manifest at `lib/harness/src/harness/studio/static/checklist/rummage/audio.json`. Audio never goes in git.

Notes from making it (14-15 October 2026):

- **No keystrokes.** Two macOS permission prompts sat over Live's dialogs all night (an agent never answers those),
  and they took every keystroke: hands' export script (Cmd+Shift+R, then typing into the Save panel) could not run.
  `liveops.py` does the same through the menu bar and accessibility only: the range from the loop brace, the Export
  dialog's controls by description, the Save panel's folder from its Where popup, the name as the field's value. It
  writes into `~/_agent_scratch/rummage/` (reachable from the Recent Place "set") and moves the file to `renders/`.
- Live keeps one note per pitch and start: two identical notes in a clip become one, so `write_notes` drops
  duplicates before `add_new_notes` and then counts what Live holds.
- `song.view.selected_track = song.master_track` can silently not take (right after a view change); the next
  `browser.load_item` then lands on whatever was selected. `liveops.select_track` reads the selection back.
- Utility's gain is called `Output` in Live 12. The Music Box rack plays about 15 dB under the other beds, hence a
  Utility at +14 dB.
- Probing presets: ten candidates on ten tracks, each playing in its own two bars, one export, then per-slot stats
  and a spectrogram (`ffmpeg -lavfi showspectrumpic`). One export per ten sounds.
