# Marrow, as a cumbia

A cover of Meshuggah's "Marrow" (Koloss, 2012) as a chicha-style cumbia, made in Ableton Live 12 Suite by hands and
checked by measurement. Anthony asked for it on 15 October 2026 ("a cumbia cover of Meshuggah's Marrow using hands
and ears from zpkt"). It is a cover, for his ears: no audio and no transcription go in git, and nothing is published.

- **The notes are Meshuggah's.** `tab.py` reads Songsterr's transcription (song 385274, revision 7918175: eight parts,
  150 BPM, 209 measures, 334.4 s; the band's upload is 335.1 s) from a local copy it fetches once.
- **The cumbia is ours** (`parts.py`): 100 BPM, Marrow's eighths kept as eighths, so the riffs keep their odd groupings
  across the cumbia's four. A güiro (a real one's long scrape and two short ones, cut from Live's "Guiro 110 bpm"
  loop) on every beat, a conga tumbao, maracas, a felt bombo, timbales, a cowbell; Lövgren's bass line; the riff on a
  chicha guitar (single coil through a phaser); a transistor organ on the off-beats, its chords taken from each riff's
  own high notes; Thordendal's solo on a Farfisa; "One Evil" and the riff's return with an accordion in thirds; the
  post-solo's F/F# clang on trumpets; an eight-string through Amp and Cabinet under the return and the outro.
  Haake's kit becomes the percussion: his kick (on the riff's F) the bombo, his snare's accents the timbales, his
  china the cowbell, his hi-hat the maracas.
- **Form**, 84 bars and a bar of tail (204 s): güiro alone (2), intro (Marrow's m1-8), main riff (m9-16), verse 1
  (m25-32), verse 2 (m41-48), "One Evil" (m49-56), verse 3 (m65-72), solo (m97-104), post-solo (m113-120), the
  riff again (m161-168), outro (m178-185), a two-bar ending (a hit, a timbale roll, the last hit).
- **Main:** EQ Eight (high-pass 30 Hz), Glue Compressor (2:1 at -14 dB), Limiter (True Peak, ceiling -2 dB: at -1
  the AAC encode reached +0.5 dBTP). The mix lands at -12.3 LUFS, -1.9 dBTP.

```bash
cd hands
uv run python scripts/marrow/tab.py fetch          # once: the transcription into ~/_agent_scratch/marrow/tab/
uv run python scripts/marrow/newset.py             # once: a new Live 12 set, MARROW_cumbia, in its own folder
uv run python scripts/marrow/make.py build         # tracks, instruments + pads, notes, mix, master (each checked)
uv run python scripts/marrow/make.py save
uv run python scripts/marrow/make.py render v3     # ~21 s -> ~/_agent_scratch/marrow/renders/marrow-cumbia-v3.wav
uv run python scripts/marrow/make.py encode v3     # AAC 192k, length and loudness checked
uv run python scripts/marrow/make.py stems --raw   # each track alone, Main's dynamics off, and the raw mix
uv run python scripts/marrow/listen.py mix|chroma|masking [--phone]|pic
```

**Measured, not heard** (`listen.py`; v3): every lone guitar and eight-string note on its written pitch (178/178,
43/43); the bass's strongest peak on its written pitch for every note (the harmonic-product estimate locks an octave
low on its upper notes); per section, the pitched stems' chroma against their notes' (harmonics included) at cosine
0.93-1.00 for guitar, organ, lead, accordion and trumpets. Each part's share of energy within 6 dB of everything else,
per section: 75-100 % for most; cowbell about 60 %; on a phone model (200 Hz-8 kHz) the güiro and congas 85-96 %,
the bombo next to nothing (a felt kick), the timbale accents 19-55 %, so v3 raised them, the cowbell and the
eight-string 2 dB. Sections run from -17.8 LUFS (the güiro alone) to -11.3 (the solo), the post-solo dipping to -13.8.

Notes from making it:

- `ops.py` loads rummage's `liveops.py` by its path: putting `rummage/` on `sys.path` made `import parts` load SH001's
  parts, and the first build named this set's tracks after SH001's.
- The Save panel reaches a folder only through its Where popup (a parent of where it is, or of a Recent Place), so a
  new folder is out of reach: `newset.py` saves the new set where the panel can go, copies it into
  `~/_agent_scratch/marrow/set/` and opens it from there; exports stay staged in rummage's folder and are moved on.
- A Drum Rack pad's Simpler has `S Start` and `S Length` (percent of the sample), which is how the güiro loop's
  strokes become one-shots (Gate mode, 40 ms release).
- Live 12's Amp calls its drive `Input Gain`.
