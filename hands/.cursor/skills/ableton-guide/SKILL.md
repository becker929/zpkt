---
name: ableton-guide
description: >-
  Crash avoidance rules, non-obvious LOM patterns, and recipes for controlling
  Ableton Live via the opendining/ableton-mcp-server execute() tool. Use when
  writing execute() code, troubleshooting LOM errors, navigating the browser,
  working with devices/parameters, or writing automation envelopes.
---

# Ableton Live MCP — Agent Guide

Use `api()` and `search_api()` for LOM property/method discovery. This skill covers what those tools can't tell you: crash patterns, gotchas, and non-obvious idioms.

---

## 0. Connection & Launch

If an MCP call returns `"Cannot reach Ableton: [Errno 61] Connection refused"` (or similar), Live is not running or the Remote Script is not loaded. Launch it from the shell:

```bash
open -a "Ableton Live 12 Standard"
```

Adjust the app name for your edition (`Suite`, `Standard`, `Intro`, or `Lite`). After launching, wait for Live to finish loading before retrying:

```bash
sleep 15   # Live takes ~10-20 s to boot; adjust as needed
```

Then retry the MCP call. If it still fails, the AbletonLiveMCP Remote Script may not be installed — see the MCP server README.

On macOS the app bundle is write-protected (`mkdir` inside `Contents/App-Resources/MIDI Remote Scripts` fails with "Operation not permitted"). Install to the User Library instead, which Live 12 also scans:

```bash
mkdir -p ~/Music/Ableton/"User Library"/"Remote Scripts"/AbletonLiveMCP
cp ableton/__init__.py ~/Music/Ableton/"User Library"/"Remote Scripts"/AbletonLiveMCP/
```

A human must then select it in **Settings → Link, Tempo & MIDI → Control Surface** (Input/Output: None). Confirm with `lsof -iTCP:16619 -sTCP:LISTEN`.

**Connected ≠ audio running.** The TCP socket works even when Live has no audio device, so check the audio engine before any playback or recording work:

```python
# call 1
song.start_playing()
# call 2, ~1 s later
result = song.current_song_time   # must be > 0
```

If `is_playing` is `True` but `current_song_time` stays at `0.0`, Live has no audio clock — no clip will launch (slots sit in `is_triggered`) and every bounce is silent. Cause: no output device (Live shows an info-bar message at the bottom of the window; e.g. the USB audio interface is unplugged). This cannot be fixed over the LOM — ask the human to fix **Settings → Audio**.

---

## 1. Crash Avoidance (Non-Negotiable)

**Rule 1 — No post-set readback.**
Never read a property in the same call that wrote it. The Live API crashes.
```python
param.value = 0.5
result = param.value   # CRASH
```
Write in one call. Read in a separate call.

**Rule 2 — No large device-parameter sweeps.**
Iterating all parameters of all devices exhausts LiveAPI memory. Limit to one device + ≤20 params per call.
```python
d = song.tracks[0].devices[0]
result = [{"name": p.name, "value": p.value} for p in d.parameters[:20]]
```

**Rule 3 — Sleep between consecutive browser loads.**
Back-to-back `load_to()` or `browser.load_item()` calls cause silent race conditions.
```python
load_to(song.tracks[0], browser.instruments, "Operator")
time.sleep(0.3)
load_to(song.tracks[1], browser.audio_effects, "Compressor")
```

**Rule 4 — `tracks` alias goes stale after mutations.**
After `create_midi_track` / `delete_track`, use `song.tracks[idx]` or `find_track(name)`.

**Rule 5 — Multi-line errors leave partial state.**
A failed block may have partially modified the set. Response includes `"warning": "Multi-line code may have partially executed."` Roll back with `song.undo()`.

**Rule 6 — Stay under 12 seconds.**
Hard timeout. `browser.packs` has thousands of items — full traversal will hit this.
Use targeted subtrees only: `browser.instruments`, `browser.drums`, `browser.audio_effects`.

**Rule 7 — No long sleeps.**
`time.sleep()` blocks the audio/UI thread. Keep sleeps ≤0.5s per call.

**Rule 8 — One VST/AU load per `execute()` call.**
Third-party plugin loads take 1–3 seconds each (scanning + UI init).
Batching multiple `load_to(t, browser.plugins, ...)` calls in one block
risks the 12-second timeout and causes duplicate devices from partial
re-execution on retry.

Safe pattern:
```python
load_to(t, browser.plugins, "Decapitator")
time.sleep(0.3)
result = "load requested"  # re-query devices in a new call — Rule 1
```

Unsafe pattern:
```python
# DON'T — 3 loads (~2s VST + 0.3s built-in + sleeps) = timeout risk
load_to(t, browser.plugins, "Decapitator")
time.sleep(0.3)
load_to(t, browser.audio_effects, "EQ Eight")
time.sleep(0.3)
load_to(t, browser.plugins, "LFOTool")
time.sleep(0.3)
```

Built-in effects (EQ Eight, Compressor, etc.) are faster (~0.3s) and
can be batched in small groups (2–3), but mixing built-in + VST loads
in one call is risky.

---

## 2. Non-Obvious Idioms

**Return data from statement blocks** — expressions are eval'd directly; statements need `result`:
```python
result = [(i, t.name) for i, t in enumerate(song.tracks)]
```

**Can't delete the last track** — loop from the end:
```python
for i in range(len(song.tracks) - 1, 0, -1):
    song.delete_track(i)
```

**Device On/Off** is always `parameters[0]`:
```python
song.tracks[0].devices[0].parameters[0].value = 1.0  # on
song.tracks[0].devices[0].parameters[0].value = 0.0  # off
```

**Set parameter by name** — don't read back in the same call (Rule 1):
```python
d = song.tracks[0].devices[0]
target = next((p for p in d.parameters if p.name == "Filter Freq"), None)
if target:
    target.value = 0.6
```

**Read all MIDI notes from a clip**:
```python
clip = song.tracks[0].clip_slots[0].clip
result = [
    {"pitch": n.pitch, "start": n.start_time, "dur": n.duration, "vel": n.velocity}
    for n in clip.get_notes_extended(0, 128, 0, clip.length)
]
```

**Rack chain traversal**:
```python
rack = song.tracks[0].devices[0]
result = [{"chain": c.name, "devices": [d.name for d in c.devices]} for c in rack.chains]
```

**Query routing types before setting** (labels are system-dependent):
```python
t = song.tracks[0]
result = {"in": [str(r) for r in t.available_input_routing_types],
          "out": [str(r) for r in t.available_output_routing_types]}
```

**`ClipSlot.fire()` starts the transport when stopped** — if the transport is
not playing, calling `clip_slots[n].fire()` immediately starts it. This means
any track or device setup that happens *after* `fire()` will execute while the
clip is already playing. For the resampling bounce workflow, **always fully
configure the resampling track (create, set routing, arm) before firing any
clips**. The correct sequence is:
1. `stop_playing()` → rewind → `stop_all_clips()`
2. **Disarm every source track** (see "Silent bounces" below)
3. Create + configure resampling track (routing, arm, monitoring)
4. Fire slot-0 clips on source tracks
5. `trigger_session_record()` (≤0.1s after fire)

#### Silent bounces (resampling take has peak 0.0)

Verified on Live 12.4.6 Suite. Each of these alone produces a fully silent take. Check in order, and judge by the **recorded file's peak** (e.g. `soundfile`), not track meters — a tight meter-polling loop once left the MCP socket stuck, and the file is the ground truth anyway.

1. **No audio clock** — see §0. `current_song_time` frozen at 0.0.
2. **Source track armed.** `trigger_session_record()` records on *every* armed track. Live auto-arms the selected MIDI track, so the source gets a new empty MIDI clip (look for a stray clip in the next slot) that replaces what it was playing. Fix: disarm sources before recording, restore after.
   ```python
   armed = [i for i, t in enumerate(song.tracks) if t.can_be_armed and t.arm]
   ```
3. **"Back to Arrangement" lit (arrangement bounces only).** `track.stop_all_clips()` (or any session launch) detaches the track from the arrangement: `song.back_to_arranger` reads `True` and the track ignores its arrangement clips. Fix: `song.back_to_arranger = False` after `stop_all_clips()` and before starting playback.

Session-view vs arrangement-view playback both record fine once 1–3 are handled. `Track.current_monitoring_state` values are `0=In, 1=Auto, 2=Off` (not `1=In`).

---

## 3. Browser

Targeted subtrees only — never search from the browser root (Rule 6).

| Subtree | Contents |
|---|---|
| `browser.instruments` | Synths, samplers (Operator, Wavetable, Simpler, etc.) |
| `browser.drums` | Drum racks and kits |
| `browser.audio_effects` | Reverb, Delay, Compressor, EQ Eight, etc. |
| `browser.midi_effects` | Arpeggiator, Chord, Note Length, etc. |
| `browser.sounds` | Presets and samples |
| `browser.plugins` | **Third-party VST/AU/VST3 plugins** (Decapitator, LFOTool, etc.) |
| `browser.packs` | Factory content — **avoid full traversal** |

`browser.plugins` children: `AUv2`, `VST`, `VST3`.
The same plugin may appear under multiple formats — `find_items()` returns
all matches. If you get duplicates, use a longer query or check the path.

**Third-party plugins live under `browser.plugins`, NOT `browser.audio_effects`.**
`browser.audio_effects` only contains Ableton's built-in effects. If `load_to()` raises
`ValueError: No loadable item matching '...'` for a known plugin, switch to `browser.plugins`:
```python
load_to(t, browser.plugins, "Decapitator")   # correct for VST/AU
load_to(t, browser.audio_effects, "EQ Eight") # correct for built-in
```

`find_item` returns `None` on no match. `load_to()` raises `ValueError` on no match.
String matching is substring+prefix ranked — use longer queries to avoid ambiguity (`"Reverb"` not `"Rev"`).
After loading, new device is at `song.tracks[idx].devices[-1]` — re-query in a new call.

For available instruments and effects names, see [references/available-devices.md](references/available-devices.md).

---

## 4. Automation (Clip Envelopes)

Not obvious from `api()` — the envelope object is obtained from the clip, not the device:

```python
clip = song.tracks[0].clip_slots[0].clip
device = song.tracks[0].devices[0]
param = next((p for p in device.parameters if p.name == "Filter Freq"), None)
if param:
    env = clip.automation_envelope(param)
    env.insert_step(0.0, 0.0, 0.2)   # (beat_time, duration, value) — duration=0 for point
    env.insert_step(4.0, 0.0, 0.8)
    env.insert_step(8.0, 0.0, 0.2)

clip.clear_envelope(param)      # clear one parameter
clip.clear_all_envelopes()      # clear all automation on clip
```

---

## 5. Arrangement View (Undocumented)

Not in `api()` — discovered via `dir(track)`. These methods exist on Track objects:

**Create clips directly in the arrangement:**
```python
t = song.tracks[0]
t.create_midi_clip(0.0, 4.0)   # (start_beat, length_beats)
```

**Copy a session clip into the arrangement:**
```python
t = song.tracks[0]
session_clip = t.clip_slots[0].clip
t.duplicate_clip_to_arrangement(session_clip, 16.0)  # (clip, dest_beat)
```

**Tile a session clip across a range:**
```python
t = song.tracks[0]
clip = t.clip_slots[0].clip
beat = 0.0
while beat < 32.0:
    t.duplicate_clip_to_arrangement(clip, beat)
    time.sleep(0.1)
    beat += 4.0
```

**Read / delete arrangement clips:**
```python
clips = list(t.arrangement_clips)
result = [{"name": c.name, "start": c.start_time, "end": c.end_time} for c in clips]

t.delete_clip(clips[0])  # pass the clip object, not an index
```

**Arrangement loop:**
```python
song.loop_start = 0.0
song.loop_length = 32.0
song.loop = True
```

`time.sleep(0.1)` between `duplicate_clip_to_arrangement` calls prevents race conditions.

---

## 6. Drum Rack Pad Operations

### Selecting a drum pad
```python
t = song.tracks[0]
dr = t.devices[0]           # Drum Rack must be devices[0]
pad = dr.drum_pads[36]      # MIDI note number (C1 = 36)
song.view.selected_track = t
time.sleep(0.1)
dr.view.selected_drum_pad = pad
```

`dr.view` has `selected_drum_pad` (read/write) and `selected_chain` (read-only).
`dr.drum_pads[note].chains` is a `Vector` — check `len(chains)` before accessing.

### Loading a sample into a pad
Use `browser.samples` (raw audio files), **NOT** `browser.sounds` (presets — those
load at the track level regardless of pad selection).  Always separate the load from
any readback (Rule 1 — the DrumRack handle goes stale post-write).
```python
dr.view.selected_drum_pad = dr.drum_pads[36]
time.sleep(0.1)
item = find_item(browser.samples, '808 Kick 1')
browser.load_item(item)
time.sleep(0.3)             # Rule 3 — sleep after browser load
result = 'load requested'   # NO readback here
```

After loading, `pad.chains[0].devices[0]` is the auto-created Simpler.

### Simpler parameter names (pad chain, device 0)
| Intent | Parameter name | Range |
|---|---|---|
| Semitone pitch | `Transpose` | -48 – 48 (direct semitones) |
| Sample start | `S Start` | 0.0 – 1.0 (normalised) |
| Sample length | `S Length` | 0.0 – 1.0 (normalised) |
| Pad volume | `Volume` | -36 – 36 (dB) |

### Loading a device onto a pad's chain
Use `song.view.selected_chain` to target the pad chain — **not** `dr.view.selected_chain`,
**not** `load_to(track, ...)` (those load at the track level).
```python
chain = dr.drum_pads[36].chains[0]
song.view.selected_chain = chain
time.sleep(0.1)
item = find_item(browser.audio_effects, 'Compressor')
browser.load_item(item)
time.sleep(0.3)
result = 'device load requested'
```

After loading, the device is at `chain.devices[-1]` (query in a new call).

### DrumPad object attributes (from `dir(pad)`)
`chains`, `delete_all_chains`, `mute`, `name`, `note`, `solo`,
`add_chains_listener`, `canonical_parent` — and the standard listener pattern.
No direct methods to load samples or add devices — use browser + view selection.

---

## 7. Sandbox Limits

| Operation | Status |
|---|---|
| File I/O (`open`, `os`, `pathlib`) | Not available — Remote Script sandbox |
| Audio metering / signal data | Not in LOM — requires M4L or real-time UDP bridge |
| Hidden params (LFO targets, macro wiring) | Requires M4L JS bridge |
| `asyncio` / `await` | No event loop in embedded Python |
| Third-party `import` | Only `Live`, `_Framework`, stdlib |
| Rack modulation routing internals | M4L bridge required |
| Export / bounce to file | No API — user must export manually (Cmd+Shift+R) |
