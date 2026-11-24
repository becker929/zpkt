"""Read and write an Ableton Live set file (.als) offline: knob values, arrangement automation, the self-checks a set
must pass before Live loads it, and the mix a saved set holds.

    file.py   load and save, tracks and devices, knobs (`resolve`), donor devices, automation; how the .als is laid out
    check.py  `check` and `list_params` (`hands als check|params`)
    mix.py    `mix_state` and `mix_lines` (`hands als mix`)

Everything is offered here as `zpkt.live.als.<name>`, as when this was one module.
"""

from zpkt.live.als.check import Report, _describe, _steps_of, check, envelopes, list_params
from zpkt.live.als.file import (
    DEFAULT_TIME,
    PLUGIN_TAGS,
    TRACK_TAGS,
    XML_DECL,
    _append,
    _envelope,
    _num,
    _value,
    add_device_from_donor,
    add_points,
    all_tracks,
    current_value,
    depth,
    devices,
    event_kind,
    find_device,
    find_track,
    is_pointee_tag,
    knob_param,
    load,
    param_element,
    param_range,
    parent_map,
    pointee_elements,
    rename_track,
    resolve,
    save,
    set_manual,
    set_speaker,
    set_steps,
    track_name,
    value_at,
    xml_hash,
)
from zpkt.live.als.mix import SILENT, mix_lines, mix_state

__all__ = [
    "DEFAULT_TIME", "PLUGIN_TAGS", "SILENT", "TRACK_TAGS", "XML_DECL", "Report", "_append", "_describe", "_envelope",
    "_num", "_steps_of", "_value", "add_device_from_donor", "add_points", "all_tracks", "check", "current_value",
    "depth", "devices", "envelopes", "event_kind", "find_device", "find_track", "is_pointee_tag", "knob_param",
    "list_params", "load", "mix_lines", "mix_state", "param_element", "param_range", "parent_map",
    "pointee_elements", "rename_track", "resolve", "save", "set_manual", "set_speaker", "set_steps", "track_name",
    "value_at", "xml_hash",
]  # fmt: skip
