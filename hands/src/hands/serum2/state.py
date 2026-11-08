"""Serum 2 state codec, verified against Serum 2.1.5 (Nov 2026).

Live stores a VST3 plug-in's state in the .als as hex under <ProcessorState> (IComponent) and
<ControllerState> (IEditController). For Serum 2 both are:

    b"XferJson\\0" + u64 header_len + JSON header + u32 raw_len + u32 2 + zstd(CBOR dict)

The header's "hash" is the md5 of the zstd bytes. A factory .SerumPreset file uses the same layout
with fileType/presetName in the header and a few GUI-only sections in the dict, so a preset can be
turned into a processor state with `preset_to_processor`.

Mod matrix (decoded from 13k routings in the factory presets): ModSlotN =
    {"source": [SOURCE_ID, index], "destModuleTypeString": "Oscillator", "destModuleID": 0,
     "destModuleParamName": "kParamVolume", "destModuleParamID": 2, "plainParams": {"kParamAmount": -100.0}}
`source` must be a 2-element list; anything else makes Serum refuse the whole state.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any

MAGIC = b"XferJson\x00"

# Mod sources: [id, 0]. Verified by rendering: Env 2 = 3, LFO 1 = 6, Macro 1 = 25; the rest follow
# Serum's source menu order (Mod Wheel, Env 1..4, LFO 1..10, Velo, Note#, Aftertouch, Poly AT,
# Noise OSC, NoteOn Rand1, Rand2, Alt, Alt2, Macro 1..8, ...).
MOD_SOURCES: dict[str, int] = {
    "mod_wheel": 1, "env1": 2, "env2": 3, "env3": 4, "env4": 5,
    **{f"lfo{i}": 5 + i for i in range(1, 11)},
    "velocity": 16, "note": 17, "aftertouch": 18, "poly_aftertouch": 19, "noise_osc": 20,
    "noteon_rand1": 21, "noteon_rand2": 22, "noteon_alt": 23, "noteon_alt2": 24,
    **{f"macro{i}": 24 + i for i in range(1, 9)},
}

# FXRack FX "type" ids (each FX dict also holds {"FX<Name>": {"plainParams": {...}}}).
FX_TYPES: dict[str, int] = {
    "Distortion": 0, "Flanger": 1, "Phaser": 2, "Chorus": 3, "Delay": 4, "Comp": 5, "Reverb": 6,
    "EQ": 7, "Filter": 8, "HyperD": 9, "Bode": 10, "Conv": 11, "Utils": 12, "Split": 13,
    "Split3": 14, "SplitMS": 15,
}

_PRESET_ONLY = ("fileType", "presetName", "presetAuthor", "presetDescription", "tags", "hash",
                "arpBankDisplayName", "clipBankDisplayName")


@dataclass
class XferBlob:
    header: dict[str, Any]
    fmt: int
    data: Any


def decode(blob: bytes) -> XferBlob:
    if not blob.startswith(MAGIC):
        raise ValueError("not an XferJson blob")
    import cbor2
    import zstandard

    n = struct.unpack("<Q", blob[9:17])[0]
    header = json.loads(blob[17:17 + n])
    rest = blob[17 + n:]
    size, fmt = struct.unpack("<II", rest[:8])
    raw = zstandard.ZstdDecompressor().decompress(rest[8:], max_output_size=size)
    return XferBlob(header, fmt, cbor2.loads(raw))


def encode(blob: XferBlob) -> bytes:
    import cbor2
    import zstandard

    raw = cbor2.dumps(blob.data)
    comp = zstandard.ZstdCompressor(level=19).compress(raw)
    header = dict(blob.header, hash=hashlib.md5(comp).hexdigest())
    hj = json.dumps(header, separators=(",", ":")).encode()
    return MAGIC + struct.pack("<Q", len(hj)) + hj + struct.pack("<II", len(raw), blob.fmt) + comp


def preset_to_processor(preset: bytes, processor_template: bytes) -> bytes:
    """A .SerumPreset file -> a processor state, using an existing state for the header/version."""
    p = decode(preset)
    t = decode(processor_template)
    data = {k: v for k, v in p.data.items() if k not in _PRESET_ONLY}
    for k in ("component", "product", "productVersion", "url", "vendor", "version"):
        if k in t.data:
            data[k] = t.data[k]
    return encode(XferBlob(t.header, t.fmt, data))


def mod_slot(source: str, dest_type: str, dest_param: str, dest_param_id: int, amount: float,
             dest_index: int = 0, source_index: int = 0) -> dict[str, Any]:
    """One mod-matrix routing. dest_param_id: see DEST_PARAM_IDS / mod_dest_ids.json."""
    return {"source": [MOD_SOURCES[source], source_index], "destModuleTypeString": dest_type,
            "destModuleID": dest_index, "destModuleParamName": dest_param,
            "destModuleParamID": dest_param_id, "plainParams": {"kParamAmount": float(amount)}}
