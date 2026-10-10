# Rig snapshots

Device-state snapshots of the Live clone, written by `../rig.py`. Schema
`hands.rig.snapshot/1`. Each file records, per device on one track: index,
name, `class_name`, `type`, its `Device On` parameter, and the watched
parameters listed in the file's `watch` block.

| File | What it is |
| --- | --- |
| `snts_kick_devices.json` | **The restore target.** Track 6 `Kick (G)` as found: Drum Rack + Decapitator + Utility ON, everything else OFF, Decap Drive 0.42 / Style 0.5, Transient Attack 0.77961 / Sustain 0.5, StandardCLIP Clipping 0.768056. |
| `snts_kick_clip_values_demo_rig.pre.json` | Auto-written restore point from the `solo-device` run that set up the clipper (Row 2) rig. Same state as above. |
| `snts_kick_clip_values_demo_rig.post.json` | The Row-2 rig itself: StandardCLIP `devices[6]` ON, Decapitator `devices[1]` OFF, Utility kept ON. Reproduce a clipper sweep by restoring this file. |

Commands:

```sh
cd ~/sandbox/autodaw/hands

# read-only: capture current state
uv run python sweeps/rig.py snapshot --track 6 --name snts_kick_devices

# isolate one device (writes <name>.pre.json first, so it is always undoable)
uv run python sweeps/rig.py solo-device --track 6 --device 6 --keep 7 \
    --name my_rig

# put a snapshot back and verify every value by read-back
uv run python sweeps/rig.py restore --from sweeps/snapshots/snts_kick_devices.json
```

Rules: `restore` refuses to run if the track's name or device count no longer
matches the snapshot. `solo-device` keeps the track's instrument (device
`type == 1`) ON, otherwise the track bounces silence. `--keep 7` holds the
`Utility` gain stage as-is, matching how the earlier SNTS kick sweeps ran.
Nothing here ever saves the Live set.
