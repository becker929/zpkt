# Handoff: finish Phase 4 (from step 2) and all of Phase 5

Written by the outgoing agent, offline, while Live was busy with another
agent's "multitrack bounce" job on the same shared instance. Everything below
was prepared WITHOUT touching Live. You are the first agent since this was
written who should actually drive Live. Read this whole file before you do.

Full background: `PLAN.md` (the phase definitions), `STATUS.md` (where things
stand), `HANDOFF.md` (deep context, esp. §4 findings and §12 the measurer),
`PROVENANCE.md` (the rig and restore target), `MAP.md` (the map itself).
This file is the fast path -- it does not replace those, it sequences them.

---

## 0. Before you touch anything

1. **Confirm Live is actually free.** Another agent may still be bouncing.
   Read-only check, safe to run anytime:
   ```bash
   python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
     "result = {'is_playing': song.is_playing, 'record_mode': song.record_mode}"
   ```
   Both must be `False`. If not, WAIT. Do not stop/start transport yourself --
   you don't know what the other agent is mid-recording. Re-check periodically.
2. **Confirm you're on the right clone and rig.** `PROVENANCE.md` §2. Track 6
   = `Kick (G)`, track 44 = `STEM_CAP`, tempo 160.
3. **Confirm the restore target still holds** before starting fresh work:
   ```bash
   cd ~/sandbox/autodaw/hands
   uv run python sweeps/rig.py snapshot --track 6 --name pre_check
   ```
   Compare by eye against `sweeps/snapshots/snts_kick_devices.json` (Decapitator
   ON 0.42/0.5, StandardCLIP OFF 0.768056, Transient Shaper OFF 0.77961/0.5,
   Utility ON, rest OFF). If it drifted, the other agent's job may have left
   state behind -- investigate before proceeding, don't just barrel through.
4. **Serialize.** One sweep at a time, start to finish (rig up, bounce,
   measure, restore, verify) before starting the next. Never run two
   Live-driving tasks concurrently, whether that's you and another agent, or
   two of your own subagents.
5. **Never save the Live set.** Snapshots read; `rig.py restore` writes
   parameter values back, never `File > Save`.
6. **Use `--tol 0.05` on every `summarize_curve.py` call from now on.**
   Phase 4 step 1 measured the real crest noise floor at 0.048 dB stdev
   (n=4, one cold-start outlier excluded -- see `HANDOFF.md` §4 and `MAP.md`).
   This replaces the old 10%-of-span guess.
7. **Watch for the cold-start bounce artifact.** Phase 4 step 1's very first
   bounce after a fresh `rig.py solo-device` call captured 250 s of audio
   instead of ~3.6 s (66 MB vs ~950 KB), wrecking its crest reading. It passed
   the silent-bounce guard (not silent, just wrong length), so the guard won't
   catch it. Eyeball `ls -la out/<id>/*.wav` after every bounce; if row 0 (or
   any row) is wildly larger than its siblings, exclude it and note it, don't
   trust its measurement.
8. **Do not rebuild tooling.** `run_sweep_stem.py`, `rig.py`, `assemble_curve.py`,
   `summarize_curve.py`, `build_rig.py` all already do what you need. If one
   seems to be missing something, re-read its `--help` before assuming you need
   to change it.
9. **Do not edit `MAP.md` / `HANDOFF.md` / `STATUS.md` mid-run.** Finish every
   task's Live work and restore first, then do the doc updates listed in
   §9 below, once, at the end (or after each task if you prefer -- just don't
   leave Live mid-experiment while you write docs).

---

## 1. Task order

Ready-to-run spec files already exist in `sweeps/`. Run them in this order.
Steps 2 and 7 need a short investigation first (instructions below); the rest
are ready as-is.

| # | Plan ref | Spec file | Ready? |
|---|---|---|---|
| 1 | Phase 4.2 floor/ceiling | `p4_floor_ceiling.sweep.json` | Ready |
| 2 | Phase 4.3 Attack inverse | `p4_attack_validate.sweep.json` | Ready |
| 3 | Phase 4.4 two-knob composition | `p4_compose.sweep.json` | Ready (needs manual pre-steps, see its `hypothesis` field) |
| 4 | Phase 4.5 Decap-on portability | `p4_decap_on_portability.sweep.json` | Ready |
| 5 | Phase 4.6 Attack fine-grid | `p4_attack_fine.sweep.json` | Ready |
| 6 | Phase 5.1 Sustain | `p5_sustain.sweep.json` | Ready |
| 7 | Phase 5.2 spectral lever (HPF) | none yet | Needs a 1-minute recon first, §3 |
| 8 | Phase 5.3 Decap Style | `p5_decap_style.sweep.json` | Ready |
| 9 | Phase 5.4 + 5.5 second instrument | none yet | Needs investigation, §4 |
| 10 | Phase 5.6 orthogonality matrix | n/a | Pure synthesis, do last, §5 |

Standard cycle for every "Ready" spec (all target track 6):

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/rig.py solo-device --track 6 --device <N> --name <task>
timeout 900 uv run python sweeps/run_sweep_stem.py --sweep sweeps/<spec>.sweep.json \
  --capture-track 44 --source-track 6 --source-input "Kick (G)"
export EARS_CMD="/Users/anthonybecker/_agent_scratch/ears_lab/.venv/bin/ears"
uv run python sweeps/assemble_curve.py --dir sweeps/out/<id> \
  --ears-cmd "uv run python sweeps/ears_shim.py" \
  --measure-keys crest_db sub_share low_share mid_share high_share air_share \
  --out sweeps/out/<id>/<id>.acceptance.ears.csv
uv run python sweeps/summarize_curve.py --csv sweeps/out/<id>/<id>.acceptance.ears.csv --tol 0.05
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

`<N>` = the device index each spec's `device_expr` targets (6, 3, or 1 --
read it off the spec file). After `restore`, ALWAYS also run a fresh
`rig.py snapshot` and diff it against `snts_kick_devices.json` (only the
`timestamp_utc` field should differ) before moving to the next task. This is
the "snapshot diff" proof the standing rules require.

---

## 2. Task 3 (Phase 4.4) walkthrough, since it's not a plain solo-device cycle

Read `p4_compose.sweep.json`'s `hypothesis` field for the full reasoning. In
short:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/rig.py solo-device --track 6 --device 3 --name p4_compose_a
uv run python sweeps/rig.py solo-device --track 6 --device 6 --keep 3 --name p4_compose_b
python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
  "d=song.tracks[6].devices[3]; p=next(p for p in d.parameters if p.name=='Attack'); p.value=0.6; result=p.value"
timeout 900 uv run python sweeps/run_sweep_stem.py --sweep sweeps/p4_compose.sweep.json \
  --capture-track 44 --source-track 6 --source-input "Kick (G)"
# ... assemble_curve.py / summarize_curve.py as usual ...
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

The `--keep 3` on the second `solo-device` call is what leaves Attack's
device ON while turning StandardCLIP ON too -- both are on together only for
this one task. The final `rig.py restore` resets everything (On-states,
Attack, Clipping) in one shot; verify by diff as usual.

---

## 3. Task 7 (Phase 5.2, spectral lever) -- do this recon first

Track 6 has TWO Eq8 instances: `devices[4]` "EQ Eight" and `devices[5]` "HPF".
Use `devices[5]` (its name says it's already meant as a highpass). First,
read-only, enumerate its parameters (do this even if Live shows busy is not a
concern -- this is a pure read):

```bash
python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
  "result = [(p.name, p.value, p.min, p.max) for p in song.tracks[6].devices[5].parameters]"
```

Find the frequency parameter for band 1 (Eq8 native params are usually named
per-band, something like `1 Frequency A`). Confirm the band's filter type is
a highpass (there is usually a paired `1 Filter Type A`-style parameter, or
a filter-on flag). Pick a sweep range that CROSSES the sub/low edge at 150 Hz
-- e.g. roughly 20-40 Hz (filter mostly out of the way) up to 300-400 Hz. Eq8
frequency params show real Hz in `value_string` since it's a native device,
so you can read the true frequency directly off the acceptance CSV.

Then write a spec file `p5_hpf.sweep.json` modeled on `p5_sustain.sweep.json`
(`device_expr: "song.tracks[6].devices[5]"`, the real param name, `start`/
`stop`/`steps` spanning your chosen Hz range, `predicted_measure: "sub_share"`,
`predicted_direction: "decreasing"`), then run the standard cycle
(`rig.py solo-device --track 6 --device 5`, etc).

---

## 4. Task 9 (Phase 5.4 + 5.5, second instrument) -- investigate before you sweep

### What's already known (don't re-derive this)

Ground-truth track index -> name (from `song.tracks`, NOT the OSC track-name
list, which is off by one somewhere -- always use this LOM enumeration):

```
7  Perc                   -- Drum Rack + Audio Effect Rack + "LPF breakdown" rack + HPF (Eq8) + Utility + NTPD Lite
8  Perc (pitched down)    -- SSL FlexVerb + Shifter (pitch-shift device, has "Pitch Coarse" -24..24) + HPF + Utility x2
10 Kick layer             -- has_midi_input=False, starts with EQ Eight -- looks like an AUDIO track (receives audio, not a standalone instrument). Weak candidate.
16 Bass SFX               -- has_midi_input=False, starts with SPAN -- also looks like an audio-only track. Weak candidate.
```

`Perc` (track 7) is the best candidate: a real standalone Drum-Rack MIDI
instrument, structurally parallel to `Kick (G)`.

**Neither `Perc` nor `Perc (pitched down)` has a session clip** in slots 0-7
(checked). That's why they can't be fired the way `Kick (G)` is today. Do NOT
try to hand-build a clip with raw LOM calls -- use the tool below.

**`build_rig.py` already solves this.** It's idempotent and auto-discovers a
trigger pattern from the track's EXISTING arrangement clip:

```bash
cd ~/sandbox/autodaw/hands
uv run python sweeps/build_rig.py --source "Perc" --check   # read-only, mutates nothing
uv run python sweeps/build_rig.py --source "Perc"            # creates the missing session clip only
```

Read `build_rig.py`'s docstring before running the write form. Important
detail: it only CREATES a capture track if none exists by the given name
(default `STEM_CAP`). Since `STEM_CAP` already exists (pointed at `Kick (G)`),
the write form will NOT touch it or its routing -- it will only add the
missing session clip to `Perc`'s slot 0, using notes auto-discovered from
`Perc`'s `arrangement_clips[0]`. Confirm this with `--check` first and read
its printed `rig_ready` / `created` fields before trusting it.

### What you still have to do yourself

1. **Repoint `STEM_CAP`'s input for the duration of this test only.**
   `build_rig.py` will not do this for you (see above). Read the current
   routing first, then set it:
   ```bash
   python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
     "result = song.tracks[44].input_routing_type.display_name"   # expect "Kick (G)"
   python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
     "tr=song.tracks[44]; rt=next(r for r in tr.available_input_routing_types if r.display_name=='Perc'); tr.input_routing_type=rt; result=tr.input_routing_type.display_name"
   ```
2. **Snapshot `Perc`'s device state before touching anything**, as a restore
   target: `uv run python sweeps/rig.py snapshot --track 7 --name perc_devices`.
3. **Pick ONE non-pitch knob on `Perc` for Phase 5.4.** The `Audio Effect
   Rack` and `LPF breakdown` rack's Macro 1-16 parameters all read 0.0 with
   generic default names -- that usually means they are UNMAPPED (turning
   them would do nothing audible). Don't trust them blind; either confirm a
   macro is actually mapped to something first, or just target `Perc`'s own
   `HPF` (`devices[3]`, Eq8) frequency parameter -- same recipe as task 7
   above, guaranteed to do something real. This is the safer default choice.
4. **For Phase 5.5 (pitch reversal retest), `Perc (pitched down)`'s `Shifter`
   device is a promising but UNVERIFIED candidate.** It has a `Pitch Coarse`
   parameter (-24..24 semitones) which is exactly the kind of knob step 5
   wants. BUT: this track also has no session clip, `has_midi_input=True`
   yet no instrument device in its chain, and its `input_routing_type` reads
   `"All Ins"` (not obviously fed by `Perc`'s audio via an internal route).
   How this track actually receives signal is NOT confirmed. Investigate
   before building anything: check `song.tracks[8].current_input_routing_type`
   vs `available_input_routing_types` for a `Perc`-sourced option, and check
   whether it has any arrangement clips at all. If it turns out to be a dead
   or unused track in this project, that is a legitimate finding -- fall back
   to a SIMPLER path instead: `Perc`'s Drum Rack pads are Simpler/Sampler
   instances, and the specific pad triggered by the discovered note (from
   `build_rig.py --check`'s `notes` field) likely has its own `Transpose`
   parameter. Enumerate `song.tracks[7].devices[0].drum_pads` (or the chain
   matching the triggered note) to find it, and sweep THAT for the pitch
   retest instead of chasing `Perc (pitched down)`. Don't burn much budget on
   this -- if neither path is clean within a reasonable number of calls, log
   what you tried and why it didn't pan out, and move on to §5. A documented
   miss is a valid outcome here, not a failure.
5. **Restore everything when done**, in this order:
   ```bash
   uv run python sweeps/rig.py restore --from sweeps/snapshots/perc_devices.json
   python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
     "tr=song.tracks[44]; rt=next(r for r in tr.available_input_routing_types if r.display_name=='Kick (G)'); tr.input_routing_type=rt; result=tr.input_routing_type.display_name"
   # delete the session clip build_rig.py added, to leave Perc exactly as found:
   python3 ~/.agents/skills/ableton-live-control/scripts/live_mcp.py \
     "song.tracks[7].clip_slots[0].delete_clip(); result='deleted'"
   ```
   Then verify: re-snapshot track 7 and diff against `perc_devices.json`
   (On-states + watched params only -- the snapshot schema doesn't cover
   clips, so confirm the clip's gone by re-checking `has_clip` separately),
   and re-check `STEM_CAP`'s routing reads `"Kick (G)"` again.

---

## 5. Task 10 (Phase 5.6, orthogonality matrix) -- last, no Live needed

Once tasks 1-9 are done and logged, build a table in `MAP.md`: rows = every
mapped knob (Decap Drive, Decap Style, Clipping, Attack, Sustain, HPF freq,
plus whatever Phase 5.4/5.5 mapped), columns = crest / sub / low / mid / high
/ air, cells = moves / holds. This is what makes the map usable by the
Assistant rung. Pure reading of existing acceptance CSVs plus writing -- no
Live required, safe to do any time, even while another agent has Live.

---

## 6. Doc updates once everything above is done

- `HANDOFF.md` §4: append one paragraph per task with its real numbers
  (mirror the style of the existing Phase 4 step 1 entry there).
- `MAP.md`: add/extend rows for every new or re-validated knob; add the
  orthogonality matrix (§5 above); mark saturating clipper rows explicitly.
- `STATUS.md`: flip Phase 4 and Phase 5 to DONE once their "done when"
  checklists in `PLAN.md` are actually met, not before.
- Do NOT touch `PLAN.md` itself -- it's the fixed plan, not a log.

## 7. If something doesn't match a prediction

Log it as a finding, don't force a pass. `PLAN.md`'s own risk notes say this
explicitly for Phase 4. The Decap Drive hump and this session's cold-start
bounce artifact are both examples of "the real result surprised us" being the
useful outcome, not a bug to hide.
