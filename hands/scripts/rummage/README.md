# SH001, the short The Rummage plays

The music for The Rummage (`docs/rummage.md`): a 32-bar short in three parts with three options each, made in Ableton
Live 12 Suite by hands and rendered as all 27 combinations. The page plays the renders (`docs/sound.md`); it never
makes or changes sound.

- **118 BPM, 4/4, 32 bars, 65.085 s. D minor, dorian colour.** Two bars a chord: Dm9, G9, Bbmaj7, A7sus4 to A7, three
  times; the last time round turns home: Dm9, G9, Bbmaj7, D(add9).
- **Arrangement:** bars 1-8 the bed alone; 9-16 drums come in (kick and hats, then the whole kit, a fill at 16);
  17-28 the bass and the full groove (extra percussion, fills at 24 and 28); 29-32 the outro (one last hit, the bass
  holds Bb then D, the bed rings out).
- **The options** (`parts.py`; names and lines for the page are in `OPTIONS`):

| Part | 1 | 2 | 3 |
|---|---|---|---|
| bed | Music box & hiss: Music Box (the tune over an eighth-note arpeggio), Chorus-Ensemble; a looping tape-noise sample | Parlour upright: Childhood Home Piano in a lopsided comp; Toy Piano Bells on the tune, an octave up, through a chorus | Branches & tin bowl: Tree Branches pad holding the chords; Tin Bowl on the tune at half speed |
| drums | Tin-can break: Rattle Kit, a broken beat | Clockwork four: Clockwork Kit, four on the floor, a ticking off-beat | Cutlery shuffle: Perc Kitchen Kit (spoons, knives, pans, glass) in triplets, a Kick Wood sample on pad 35 |
| bass | Round sub: Sub Mellow through Saturator's Bass Shaper | Rubber band: Tension Rubber Bass, plucked sixteenths | Bowed gut: Cat Gut Bass through a hard-curve Saturator |

  Everything is Live's own Core Library (the Lost and Found pack is not installed on this Mac): presets, three of its
  kits and two of its samples. No purchased audio, nothing from Anthony's library.
- **Main:** EQ Eight (high-pass 32 Hz), Glue Compressor (2:1 at -12 dB, 10 ms, auto release), Limiter (True Peak,
  ceiling -1.8 dB). Renders land around -14 to -15 LUFS; the page's `gain_db` matches them to -14.

```bash
cd hands
# in Live: File > New Live Set (Live's default: MIDI tracks, Reverb and Delay returns), then
uv run python scripts/rummage/make.py save            # Save As SH001_rummage into ~/_agent_scratch/rummage/set/
uv run python scripts/rummage/make.py build           # tracks, instruments, notes, mix, master (each step checked)
uv run python scripts/rummage/make.py save
uv run python scripts/rummage/make.py stems           # each option alone (for the balance), 9 exports
uv run python scripts/rummage/make.py render all      # the 27 combos, ~18 s each
uv run python scripts/rummage/make.py measure         # length, peak, true peak, LUFS
uv run python scripts/rummage/make.py encode          # AAC 192k .m4a named by content + audio.json
```

`build` takes steps too (`build notes`, `build notes:upright` for one track, `build mix master`), and `combo 1-2-3`
sets the mutes for one combo. A combo un-mutes exactly its three options' tracks; everything else in the set is the
same for all 27, so they line up sample for sample.

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
