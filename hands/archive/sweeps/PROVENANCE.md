# Provenance and relaunch recipe

Phase 2 of `PLAN.md`. Everything here is verified, not remembered.

---

## 1. The clone (copy-on-write, never saved)

| | |
|---|---|
| ORIGINAL (Anthony's real work) | `/Users/anthonybecker/_tmsmsm/daw-library/experimental projects/SNTS_4-22/` |
| CLONE (all our work) | `/Users/anthonybecker/_agent_scratch/SNTS_4-22/` |
| Copy command | `cp -Rc "<original>" /Users/anthonybecker/_agent_scratch/SNTS_4-22` (`-c` = APFS clone, instant + copy-on-write) |

**The original is PROVEN untouched.** Verified by checksum, not by trust:

```
md5 "<original>/SNTS Style track.als" = bed025943c269a9468b3fa0765053507
md5 "<clone>/SNTS Style track.als"    = bed025943c269a9468b3fa0765053507
```

All four `.als` files in the original still carry their April mtimes
(Apr 13 05:21, Apr 14 07:54, Apr 21 07:05, Apr 22 17:30) and their original
byte sizes, matching the clone exactly. We never saved the Live set, so nothing
was written back on either side.

The project contains four set versions; the newest is
`SNTS Style track 2026-04-21.als`.

## 2. How to relaunch

1. Confirm the clone exists at `/Users/anthonybecker/_agent_scratch/SNTS_4-22/`.
   If `_agent_scratch` was wiped, re-clone with the `cp -Rc` line above.
2. Open a set from the CLONE directory — never from `_tmsmsm`. Double-check the
   Live title bar / window path says `_agent_scratch` before touching anything.
3. Confirm Path A (OSC) is up:
   ```bash
   python3 ~/.agents/skills/ableton-live-control/scripts/live.py /live/song/get/track_names
   ```
   Expect 45 names ending in `STEM_CAP`, with `Kick (G)` at index 6.
4. Confirm Path B (LOM/MCP) is up:
   ```bash
   nc -z 127.0.0.1 16619 && python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py "result = song.tempo"
   ```
   Expect `160.0`. `AbletonLiveMCP` is Control Surface row 3 (In/Out: None) and
   that choice persists across restarts.
5. Confirm the device state matches the original snapshot:
   ```bash
   cd ~/sandbox/autodaw/hands
   uv run python sweeps/rig.py snapshot --track 6 --name check
   # diff sweeps/snapshots/check.json against sweeps/snapshots/snts_kick_devices.json
   ```

## 3. The rig

| Piece | Where |
|---|---|
| Source instrument | `Kick (G)` = `song.tracks[6]` (standalone Drum-Rack MIDI kick) |
| Source clip | `song.tracks[6].clip_slots[0]` (SESSION clip — session playback is the reliable one here) |
| Capture track | `STEM_CAP` = `song.tracks[44]`, input routing = `"Kick (G)"` |
| Tempo | 160 BPM |

If `STEM_CAP` is missing, create an audio track at the end, name it `STEM_CAP`,
set its `input_routing_type` to the display name `Kick (G)`, and leave it
disarmed. `run_sweep_stem.py --capture-track 44` arms and disarms it per run.

Swept devices on track 6:

| Device | Param of interest |
|---|---|
| `devices[1]` Decapitator | `Drive`, `Style` |
| `devices[3]` kHs Transient Shaper (VST) | idx 1 `Attack`, idx 3 `Sustain` |
| `devices[6]` StandardCLIP | `Clipping` (threshold_dB = 144*value - 120) |

## 4. Original device state = the restore target

`sweeps/snapshots/snts_kick_devices.json` records all 10 devices on track 6:
name, class, `On` value, and the watched params. Verified restore target as of
the Phase 3 round-trip test:

- Decapitator **ON**, Drive 0.42, Style 0.5
- StandardCLIP **OFF**, Clipping 0.768056
- kHs Transient Shaper **OFF**, Attack 0.77961, Sustain 0.5
- Utility **ON**; all remaining devices OFF

Restore and VERIFY after every experiment:

```bash
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

`restore` re-reads every value and exits nonzero on mismatch, so a restore is
proven rather than assumed.

## 5. Sweep provenance — spec ↔ out dir index

Sidecar completeness was audited: **zero orphan wavs** (every `.wav` has its
`.params.json`) across all out dirs.

| out dir | spec | rows | wavs | one-line finding |
|---|---|---:|---:|---|
| `snts_kick_decap_drive_v1` | `snts_kick_decap_drive.sweep.json` | 11 | 11 | Drive 0..1. crest HUMPED (max ~11.1 dB @ 0.6); sub_share U-shaped, min 0.558 @ 0.6. Not invertible. |
| `snts_kick_decap_drive_fine_v2` | `snts_kick_decap_drive_fine.sweep.json` | 13 | 13 | Drive 0.4..0.7 refine. Confirmed the 0.6 hump is real, not a grid artifact. |
| `snts_kick_clip_thresh_v1` | `snts_kick_clip_thresh.sweep.json` | 13 | 13 | Clipping 0.6..0.9. **The good knob**: clean monotonic crest S-curve 4.3→8.76 dB, sub_share ~flat (orthogonal). |
| `snts_kick_clip_validate_v1` | `snts_kick_clip_validate.sweep.json` | 3 | 3 | Inverse-table validation. Targets 5/6/7 dB → measured 5.06/5.99/7.11. PASS. |
| `snts_kick_clip_values_demo_v1` | `snts_kick_clip_values_demo.sweep.json` | 2 | 2 | Demo of the explicit `values` list. Doubles as an n=2 cross-session repeat: crest reproduced to 0.015 dB. |
| `snts_kick_transient_attack_v1` | `snts_kick_transient_attack.sweep.json` | 11 | 11 | Attack 0..1. Biggest crest lever (span 6.7 dB, peak 15.48 @ 0.9) but sub-COUPLED (0.878→0.360). Invertible only 0.5..0.9. |
| `kick_pitch_wide_v1` | `kick_pitch_wide.sweep.json` | 13 | 13 | SYNTHETIC. Transpose 0..+36 st. sub_share monotonic DECREASING (reversal vs the research register). |
| `kick_pitch_v1` | `kick_pitch.sweep.json` | 11 | 11 | SYNTHETIC, **KNOWN DUD**: range −10..+10 st too narrow, curve saturated flat. Do not cite. |
| `roar_drive_v1` | `roar_drive.sweep.json` | 11 | **0** | Path-A param-only run on an OLD set. No audio at all; every sidecar has `bounce: null`. Unmeasurable. Also its spec now fails to load (missing `device_expr`). Re-run or retire. |
| `live_multitrack_bounce_v1` | (none — `bounce_multitrack.py`) | 0 | 0 | Empty. Leftover scaffold dir. |

Two dirs are NOT spec-linked-and-complete: `roar_drive_v1` (no wavs) and
`live_multitrack_bounce_v1` (empty). Both are recorded above rather than
deleted, because the sidecars in `roar_drive_v1` are still a valid record of a
parameter axis — they just carry no measure.

## 6. The ears lab: home, rebuild, and pinning

**Decision: keep the lab in `_agent_scratch`, but never depend on it.**

The rationale: `sweeps/ears_shim.py` lives in the repo and degrades gracefully.
With `$EARS_CMD` set it uses real ears' band shares; without it, it falls back
to `measure_local`'s band math, which Phase 1 proved agrees to 3.2e-08. So a
wiped `_agent_scratch` costs corpus exactness, never a broken pipeline. That is
a better property than copying a 220 KB lock plus a venv into the repo.

Rebuild the lab:

```bash
cd /Users/anthonybecker/_agent_scratch/ears_lab   # or wherever the ears source is
uv sync                                           # uv.lock IS the pin
.venv/bin/ears analyze <wav> --json --no-embeddings
```

`uv.lock` (220 KB, in the lab root) is the authoritative pin. **Copy it
somewhere durable if `_agent_scratch` is at risk** — it is the only thing that
reproduces the environment exactly.

Resolved versions actually installed (read from `site-packages/*.dist-info`,
2026-09-08):

| package | version |
|---|---|
| librosa | 1.0.0 |
| numba | 0.67.0 |
| numpy | 2.5.3 |
| pyloudnorm | 0.2.0 |
| rich | 15.0.0 |
| scipy | 1.18.1 |
| soundfile | 0.14.0 |
| typer | 0.27.2 |

Note `numpy 2.5.3` / `librosa 1.0.0` are recent majors. Real ears loads audio as
**float32** while `measure_local` uses float64 — that dtype difference, not the
library versions, is the whole source of the ~1e-8 measurement residual
(see `PHASE1_REPORT.md`).

## 7. Safety rules that produced this state

- Work only on the COW clone. Never open or save anything under `_tmsmsm`.
- Never save the Live set (no `song.save`, no Cmd-S). The map is built from
  transient state; the clone's `.als` files stay pristine.
- Restore every device `On` and every swept param, then VERIFY by read-back.
- Anything that must survive goes in the repo, not `_agent_scratch`.
