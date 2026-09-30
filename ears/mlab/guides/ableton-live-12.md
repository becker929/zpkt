# Ableton Live 12 in this lab

Anthony uses Live 12 Suite. This guide covers export settings, devices for
mastering, and how a Live-driving session hands renders to the lab.
Device details are from memory and prior sessions. Where marked, verify in the manual:
ableton.com/en/manual (the pages could not be fetched on 2026-09-25).

## Export settings

Open with File → Export Audio/Video (Cmd+Shift+R).

| Purpose | Rendered Track | Bit depth | Dither | Normalize | Sample rate |
|---|---|---|---|---|---|
| Premaster for the lab | Main | 32-bit float | none | off | project (44.1 kHz for HW002) |
| Stem or device render for a hypothesis | the track, or "Selected Tracks Only" | 32-bit float | none | off | project |
| Final master for YouTube | Main (with the master chain on) | 24-bit | none | off | 48 kHz for video |
| A 16-bit file (only if asked) | Main | 16-bit | TPDF-type ("Triangular") or POW-r, once | off | as asked |

Also: set the loop brace to the section first. Leave "Include Return and Main Effects" on for mixes, off for dry device renders.
Keep one bar of pre-roll and the whole tail. Add a short fade at the Short's edges (L-004).

## Mastering devices in Live

| Device | Use | Lab tool to measure it |
|---|---|---|
| EQ Eight | tonal moves, low cut at ~15 Hz, M/S | `mlab eq-diff` with the EQ probe |
| Glue Compressor | gentle bus glue | `mlab comp-probe` |
| Compressor | precise peak/RMS compression, lookahead | `mlab comp-probe` |
| Limiter (12.1+) | final ceiling; use True Peak mode | `mlab measure` true peak, `mlab deliver` |
| Utility | gain staging, width, mono bass | `mlab spectrum` stereo table |
| Spectrum | visual check only | — |

Anthony's own plugins seen in HW002: Decapitator, StandardCLIP, Roar, Dist COLDFIRE,
ValhallaSupermassive, SSL Native FlexVerb, LFOTool (site records, 2026-09).

## Measuring a Live device (no automation needed)

1. `python3 -m mlab probe` writes `audio/renders/probes/comp_probe.wav` and `eq_probe_pink.wav`.
2. Drag a probe onto an empty audio track. Add the device. Set makeup to 0 dB.
3. Export that track (32-bit float) into `audio/inbox/`.
4. `python3 -m mlab comp-probe audio/renders/probes/comp_probe.wav audio/inbox/<render>.wav`
   or `python3 -m mlab eq-diff audio/renders/probes/eq_probe_pink.wav audio/inbox/<render>.wav`.
5. Log the numbers in `LEARNINGS.md` as a device map row.

## Driving Live from code (the earlier rig)

A native Claude session on the Mac drove Live in September 2026 (site notes 7 and 10).
It used OSC for top-level parameters and the Live Object Model over MCP for everything else.
Sets were opened as copies under `~/_agent_scratch/`, never saved.
The skill lives at `~/.agents/skills/ableton-live-control/` on that Mac, with `scripts/export_audio.applescript`.

That session is the "hands". This lab is the "ears". The hand-off:

- The hands render variants into `~/Music/hw002-mastering-lab/audio/inbox/`,
  named `<set>__<track>__<param>=<value>.wav`, with a `.params.json` sidecar.
- A hypothesis YAML lists them as `file:` variants.
- `engineer hyp run` measures and judges them.

This Cowork session cannot do the hands' part (L-001). Its shell is a Linux VM.

## Reading a set without Live

`python3 -m mlab als <copy-of-set>.als` lists tracks, devices (on/off), faders and the main chain.
It flags a limiter left on Main, faders above +3 dB, and switched-off devices.
It needs the `.als` file in a connected folder. `~/_tmsmsm/Active Tracks/HW002/` is not connected yet.
