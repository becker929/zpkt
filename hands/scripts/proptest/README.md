# Property testing, as techno

hikikomorphism's Bluesky post "trial run: using suno to generate voiceovers for informational visualizations"
(https://bsky.app/profile/hikikomorphism.bsky.social/post/3mxznpbxbd22y) is a 92.7 s explainer video of their write-up
"Property Testing with Agent Swarms". The audio is a Suno narration over a Suno bed. Anthony asked on 16 October 2026:
"Add vec2 kick drum and drum samples plus sampled bass to make this into proper techno."

The voice and the video are theirs, so no audio goes in git. The set, the stems and the renders live in
`~/_agent_scratch/hiki/`.

## What was made

- **Kept:** the narration, exactly where it was, so the new audio still matches the video (the render's voice is
  0 ms from the post's own audio by cross-correlation). Also the bed: an F pedal with C, D♭ and sometimes E/A above
  it. It is high-passed at 120 Hz and ducked by the kick (a sidechained Compressor), so the new bass owns the low end.
  demucs (htdemucs_ft) split the post's audio into voice and bed.
- **Added, all VEC2:** Clubby kick 118 (F1 + 69 ct, tuned down to F), offbeat bass 126 F (F1) with 129 F as a brighter
  layer in the drop, closed hat 03, open hat 041, clap 042, ride 18, crash 06, reverse cymbals 10 and 07. Each sample
  sits in its own Simpler, loaded from its file (`replace_sample`).
- **Grid:** 160 BPM, the bed's own tempo. The video was cut from takes with different phases, so the bed is placed in
  five pieces, each cut at a scene change and nudged (−10 to −120 ms) to where its attacks best match the rendered
  kick. listen.py checks the result: within ±3 ms in every section with a groove.
- **Form follows the scenes** (`parts.py`). The "Write one. Read it. Write two. Read again." passage gets one hit per
  operation and no groove, then a clap roll and a reverse cymbal into the drop on "the write failed to invalidate the
  cache". "Four operations remain" gets a bar of air, then four hits.

## Versions

| | change | LUFS | spread of section medians | voice over music, 1-4 kHz |
|---|---|---|---|---|
| v1 | first build | -11.6 | 2.0 LU (drop no louder than C) | +2.9 to +10.7 dB |
| v2 | clap down 3 dB and wetter; hats and ride high-passed at 2 kHz; voice +1.5 dB; kick velocity by section; bright bass layer; less limiting | -10.8 | 2.7 LU | +3.8 to +12.4 |
| v3 | bed pieces refit against the rendered kick; softer intro; lighter outro | -10.9 | 2.8 LU | +3.9 to +13.4 |
| v4 | the last bed piece −4 dB; no ride under the closing line | -10.9 | 2.8 LU | +4.5 to +13.4 |

The post's own mix has a spread of 1.5 LU. The narration never stops, so it sets a floor under every section: the
music stem alone has an LRA of 5.8 LU, the mix 2.4.

## Running it

```bash
cd hands
uv run python scripts/proptest/newset.py                # once: a new Live 12 set, PROPTEST_techno
# copy the samples and the two demucs stems ("proptest voice.wav", "proptest bed.wav") into its Samples/Imported
uv run python scripts/proptest/make.py build            # tracks audio instruments sidechain notes mix master
uv run python scripts/proptest/make.py save
uv run python scripts/proptest/make.py render v4        # export beats 4-256, trimmed to the files' 0 s and 92.7 s
uv run python scripts/proptest/make.py stems voice music kick
uv run python scripts/proptest/listen.py ~/_agent_scratch/hiki/renders/proptest-v4.wav
uv run python scripts/proptest/make.py mux v4           # .m4a, and the post's video with the new audio (.mp4)
```

## Notes from making it

- VEC2 sits in iCloud Drive, which the shell cannot read, but Live can. The samples were copied by `shutil` calls
  inside Live, two files per LOM call: iCloud fetches files on demand, and 25 in one call passed the 12 s limit.
- `Track.create_audio_clip(path, beat)` places a file in the arrangement. Unwarping the clip moves its start marker
  to the first transient (0.51 s for the voice). Once unwarped, the markers are in file seconds: set the end, then
  the start. If a later clip overlaps an earlier one on the same track, Live trims the earlier one.
- Live's Export dialog only takes whole beats, so the render exports beats 4-256 and is cut at the files' 0 s.
- Compressor's sidechain is reachable through the LOM (`input_routing_type`, `input_routing_channel`). Its Ratio
  shows "inf : 1" at the top, which breaks liveops' display-unit search. The raw value is 1 − 1/ratio.
- Through Hammerspoon, `return value of (…) as text` fails ("Can't make «class valL» … into type text"), so
  liveops' Export dialog reads now fetch into a variable first. That route also sometimes stalls for one to three
  minutes on the first call after a pause. The guard here retries only that case.
- Pressing a Live dialog button with Hammerspoon's AXPress blocks Hammerspoon for a while. Use the dialog's own
  helpers, or wait.
- An STFT onset envelope was needed to measure the bed against the kick. A band-passed amplitude envelope gave
  correlations near 0.1, which is noise.
