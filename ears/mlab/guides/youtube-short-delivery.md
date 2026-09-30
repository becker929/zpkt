# Delivering HW002 as a YouTube Short

## The target, as far as it is known

| Item | Value | Basis |
|---|---|---|
| Length | up to 3 minutes (the demo is 84 s) | YouTube Blog, October 2024 (tier 5, checked 2026-09-25) |
| Upload audio | AAC-LC or Opus, stereo, 48 kHz, 384 kb/s for stereo | YouTube Help, "Recommended upload encoding settings" (tier 5, checked 2026-09-25) |
| Loudness | turned down to about -14 LUFS if louder; never turned up | observed behaviour (tier 4–6) |
| Served codecs | AAC ~128 kb/s and Opus ~130–160 kb/s | observed stream formats (tier 5–6) |
| Where it plays | phones first | assumption; plan for it |

## The master spec (working, from L-009–L-013)

- Integrated loudness: -14 to -11 LUFS. Louder than -14 is turned down anyway.
- True peak: -1.5 dBTP ceiling, Limiter in True Peak mode. AAC adds about 0.5 dB.
- High-pass at about 15 Hz first in the chain (hygiene; L-011).
- Fades of at least 10 ms at both ends (L-004).
- Low end mono below about 120 Hz; the demo's 0.86 correlation is fine.
- Export 24-bit, 48 kHz for the video editor.

## Check before upload

```
python3 -m mlab premaster audio/inbox/HW002_short_master.wav   # expect WARN on PLR only: it is a master
python3 -m mlab deliver   audio/inbox/HW002_short_master.wav   # no codec overs; YouTube gain near 0
python3 -m mlab measure   audio/inbox/HW002_short_master.wav --codecs
```

## Check after upload (closes the loop on the platform model)

1. Upload unlisted. Wait for processing.
2. Right-click the player → "Stats for nerds". Read "Volume / Normalized" and "content loudness".
3. Record both numbers in `LEARNINGS.md`. Compare with `mlab deliver`'s YouTube gain.
4. If they disagree by more than 1 dB, fix `mlab/delivery.py` `PLATFORMS` and say why.

## Instagram and TikTok

Their normalisation is undocumented. Upload the same master and note what you hear.
Do not make a separate louder master for them until a measurement says to.

## Sources

- YouTube Help, "Recommended upload encoding settings", support.google.com/youtube/answer/1722171 (tier 5).
- YouTube Blog, "Tall updates coming to Shorts", October 2024 (tier 5).
- Critical Listening Lab, "YouTube loudness normalization" (tier 6; observed behaviour).
