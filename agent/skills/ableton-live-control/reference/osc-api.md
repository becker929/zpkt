# AbletonOSC command reference (Live 12, release build)

Exhaustive list of OSC addresses exposed by AbletonOSC as installed at
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`. Live listens on **UDP
11000** and sends replies to **UDP 11001**.

Send with the bundled client:

```sh
python3 scripts/live.py <address> [args...]
```

## Reply semantics (important)

- **`get/*` addresses reply** with the value(s). The client auto-waits for these.
- **`set/*` and method calls do NOT reply** (fire-and-forget). The client sends
  and returns immediately. Verify effects with a follow-up `get`.
- **Index echo:** `track`, `clip`, `clip_slot`, `device`, and `scene` `get`
  replies **prepend the index argument(s)** you passed. E.g.
  `/live/track/get/name 0` → `0  "1-Audio"`; `/live/clip_slot/get/has_clip 2 8`
  → `2 8 1`. `song`, `application`, and `view` gets return the bare value.
- **Listeners** (`start_listen/*`) push updates asynchronously to the matching
  `/live/<obj>/get/<prop>` address; the client's `--listen` mode streams them.
- A handler that raises (e.g. bad args) sends **no** reply — the request times
  out. Fix the args rather than retrying.

## Argument typing (client)

Bare tokens auto-type: int, then float, else string. Force with a prefix:
`i:42` `f:3.14` `s:120` (keeps `120` a string).

---

## Application

| Address | Args | Returns |
|---|---|---|
| `/live/test` | — | `"ok"` (health check) |
| `/live/application/get/version` | — | `major minor` (e.g. `12 4` — **no patch component**) |
| `/live/application/get/average_process_usage` | — | float |

## Song — properties

`get`/`set`/`start_listen`/`stop_listen` on: (rw unless noted)

`arrangement_overdub`, `back_to_arranger`, `clip_trigger_quantization`,
`current_song_time`, `groove_amount`, `is_ableton_link_enabled`, `loop`,
`loop_length`, `loop_start`, `metronome`, `midi_recording_quantization`,
`nudge_down`, `nudge_up`, `punch_in`, `punch_out`, `record_mode`, `root_note`,
`scale_name`, `session_record`, `signature_denominator`, `signature_numerator`,
`tempo`.

Read-only: `can_redo`, `can_undo`, `is_playing`, `song_length`,
`session_record_status`.

```sh
python3 scripts/live.py /live/song/get/tempo
python3 scripts/live.py /live/song/set/tempo 128
python3 scripts/live.py /live/song/set/metronome 1
```

## Song — methods (no reply)

`capture_and_insert_scene`, `capture_midi`, `continue_playing`,
`create_audio_track`, `create_midi_track`, `create_return_track`,
`create_scene`, `delete_return_track`, `delete_scene`, `delete_track`,
`duplicate_scene`, `duplicate_track`, `force_link_beat_time`, `jump_by`,
`jump_to_prev_cue`, `jump_to_next_cue`, `redo`, `re_enable_automation`,
`set_or_delete_cue`, `start_playing`, `stop_all_clips`, `stop_playing`,
`tap_tempo`, `trigger_session_record`, `undo`.

Many take an optional index arg (e.g. `create_midi_track -1` appends;
`delete_track 3`; `jump_by 4.0`).

```sh
python3 scripts/live.py /live/song/start_playing
python3 scripts/live.py /live/song/create_midi_track -1
python3 scripts/live.py /live/song/undo
```

## Song — bulk / structure

| Address | Args | Notes |
|---|---|---|
| `/live/song/get/num_tracks` | — | int |
| `/live/song/get/num_scenes` | — | int |
| `/live/song/get/track_names` | `[start] [end]` | list of names |
| `/live/song/get/track_data` | `index_min index_max prop...` | bulk read. **props must be `obj.prop`**, e.g. `track.name track.mute clip.name device.name`. Use `-1` for index_max = all. |
| `/live/song/get/scenes/name` | — | list |
| `/live/song/get/cue_points` | — | list |
| `/live/song/cue_point/add_or_delete` | — | |
| `/live/song/cue_point/jump` | `index` | |
| `/live/song/cue_point/set/name` | `index name` | |
| `/live/song/export/structure` | — | writes a JSON structure dump to disk (not audio) |
| `/live/song/start_listen/beat` / `stop_listen/beat` | — | per-beat tick stream |

```sh
python3 scripts/live.py /live/song/get/track_data 0 -1 track.name track.mute
```

## Track

First arg is always the **track index**. `get` replies echo the index.

Read-only props: `can_be_armed`, `fired_slot_index`, `has_audio_input`,
`has_audio_output`, `has_midi_input`, `has_midi_output`, `is_foldable`,
`is_grouped`, `is_visible`, `output_meter_level`, `output_meter_left`,
`output_meter_right`, `playing_slot_index`.

Read-write props: `arm`, `color`, `color_index`, `current_monitoring_state`,
`fold_state`, `mute`, `solo`, `name`. Mixer rw: `volume`, `panning` (0.0–1.0),
`send` (via `/live/track/get|set/send  track_idx send_idx [value]`).

Methods: `/live/track/stop_all_clips track`, `/live/track/delete_device track device_idx`.

Counts / bulk (per track):
`/live/track/get/num_devices track`,
`/live/track/get/devices/name|class_name|type|can_have_chains track`,
`/live/track/get/clips/name|length|color track`,
`/live/track/get/arrangement_clips/name|length|start_time track`,
`/live/track/delete_clip track scene`.

Routing (per track):
`available_input_routing_types`, `available_input_routing_channels`,
`available_output_routing_types`, `available_output_routing_channels` (get),
and `input_routing_type`, `input_routing_channel`, `output_routing_type`,
`output_routing_channel` (get/set — value is the routing display string).

```sh
python3 scripts/live.py /live/track/get/name 0
python3 scripts/live.py /live/track/set/volume 0 0.7
python3 scripts/live.py /live/track/set/mute 0 1
python3 scripts/live.py /live/track/get/devices/name 2
```

## Clip slot

Args: `track_index scene_index`. `get` replies echo both indices.

Read-only: `has_clip`, `controls_other_clips`, `is_group_slot`, `is_playing`,
`is_triggered`, `playing_status`, `will_record_on_start`. RW: `has_stop_button`.

Methods:
`/live/clip_slot/fire track scene`,
`/live/clip_slot/stop track scene`,
`/live/clip_slot/create_clip track scene length` — **MIDI tracks only**; fails
silently on audio tracks,
`/live/clip_slot/delete_clip track scene`,
`/live/clip_slot/duplicate_clip_to track scene target_track target_scene`.

## Clip

Args: `track_index scene_index [...]`.

Read-only: `end_time`, `file_path`, `gain_display_string`, `has_groove`,
`is_midi_clip`, `is_audio_clip`, `is_overdubbing`, `is_playing`, `is_recording`,
`is_triggered`, `length`, `playing_position`, `sample_length`, `start_time`,
`will_record_on_start`.

Read-write: `color`, `color_index`, `end_marker`, `gain`, `launch_mode`,
`launch_quantization`, `legato`, `loop_end`, `loop_start`, `looping`, `muted`,
`name`, `pitch_coarse`, `pitch_fine`, `position`, `ram_mode`, `start_marker`,
`velocity_amount`, `warp_mode`, `warping`.

Methods: `/live/clip/fire`, `/live/clip/stop`, `/live/clip/duplicate_loop`,
`/live/clip/remove_notes_by_id` (each prefixed with `track scene`).

### Notes

- Add: `/live/clip/add/notes track scene  pitch start dur velocity mute  [pitch start dur velocity mute ...]`
  (5 values per note; repeatable).
- Read: `/live/clip/get/notes track scene [pitch_start pitch_span time_start time_span]`
  → flat list of `pitch start dur velocity mute` per note.
- Remove: `/live/clip/remove/notes track scene [pitch_start pitch_span time_start time_span]`.

```sh
# create a 4-beat MIDI clip on track 2 scene 0, add a C3 quarter note, read back
python3 scripts/live.py /live/clip_slot/create_clip 2 0 4
python3 scripts/live.py /live/clip/add/notes 2 0 60 0 1 100 0
python3 scripts/live.py /live/clip/get/notes 2 0
```

## Device

Args: `track_index device_index [...]`.

Props (read-only): `class_name`, `name`, `type`.

Parameters:
- `/live/device/get/num_parameters track dev`
- `/live/device/get/parameters/name track dev` (all names)
- `/live/device/get/parameters/value|min|max|is_quantized track dev` (all)
- `/live/device/get/parameter/name|value|value_string track dev param_idx`
- `/live/device/set/parameter/value track dev param_idx value`
- `/live/device/set/parameters/value track dev v0 v1 v2 ...` (all at once)
- `/live/device/start_listen/parameter/value track dev param_idx` (+ stop)

```sh
python3 scripts/live.py /live/device/get/name 2 0
python3 scripts/live.py /live/device/get/parameters/name 2 0
python3 scripts/live.py /live/device/set/parameter/value 2 0 0 1.0
```

## Scene

Args: `scene_index`. Read-only: `is_empty`, `is_triggered`. RW: `color`,
`color_index`, `name`, `tempo`, `tempo_enabled`, `time_signature_numerator`,
`time_signature_denominator`, `time_signature_enabled`.

Methods: `/live/scene/fire scene`, `/live/scene/fire_as_selected scene`,
`/live/scene/fire_selected`.

## View

`/live/view/get/selected_track|selected_scene|selected_clip|selected_device`
and the matching `set` (value = index). View gets return the bare index (no echo).

```sh
python3 scripts/live.py /live/view/set/selected_track 3
python3 scripts/live.py /live/view/get/selected_track
```

## MIDI map

`/live/midimap/map_cc ...` — advanced; maps a CC to a parameter. See
`abletonosc/midimap.py`.

---

## Not available over OSC / LOM

- **Audio export / bounce.** The Live Python API has no render function. A full
  post-FX mixdown must be driven through Live's native File → Export Audio/Video
  dialog (GUI automation). See `SKILL.md` → "Audio export".
- **Opening/saving Live sets** programmatically (LOM does not expose it).
- Live's full patch version string (only major.minor over OSC).
