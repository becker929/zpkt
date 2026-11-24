"""Load, inspect, and batch-configure devices on Ableton Live tracks."""

from __future__ import annotations

from typing import Any

from hands.live.inlive import tracks as named_tracks
from hands.live.transport import McpTransport


def _track_expr(track: str | int) -> str:
    if isinstance(track, int) or (isinstance(track, str) and track.isdigit()):
        return f"song.tracks[{int(track)}]"
    return named_tracks.track_expr(track)


def _device_expr(track_expr: str, device: str | int) -> str:
    if isinstance(device, int) or (isinstance(device, str) and device.isdigit()):
        return f"{track_expr}.devices[{int(device)}]"
    return f"next(d for d in {track_expr}.devices if d.name == {device!r})"


def load_device(
    client: McpTransport,
    track: str | int,
    device_name: str,
    category: str = "instruments",
) -> dict[str, Any]:
    """Load a device from Live's browser onto a track."""
    t_expr = _track_expr(track)
    folder_expr = "browser.instruments" if category == "instruments" else "browser.audio_effects"

    code = f"""
import time
_t = {t_expr}
song.view.selected_track = _t
_folder = {folder_expr}

def _find_item(parent, name):
    for c in parent.children:
        if c.name.lower() == name.lower():
            return c
        if hasattr(c, "children") and c.children:
            found = _find_item(c, name)
            if found is not None:
                return found
    return None

_item = _find_item(_folder, {device_name!r})
if _item is None:
    raise ValueError(f"Device {{ {device_name!r} }} not found in {{ {category!r} }}")

browser.load_item(_item)
time.sleep(0.2)
_dev = _t.devices[-1] if _t.devices else None
result = {{
    "track": _t.name,
    "device": _dev.name if _dev else None,
    "device_index": len(_t.devices) - 1,
}}
"""
    return client.run(code)


def set_parameters(
    client: McpTransport,
    track: str | int,
    device: str | int = 0,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Batch-set multiple device parameters in a single atomic LOM execution."""
    if not params:
        return {"track": str(track), "device": str(device), "applied": []}

    t_expr = _track_expr(track)
    d_expr = _device_expr(t_expr, device)

    code = f"""
_t = {t_expr}
_d = {d_expr}
_by_name = {{p.name: p for p in _d.parameters}}
_by_lower = {{p.name.lower(): p for p in _d.parameters}}
_applied = []

for _k, _v in {params!r}.items():
    _p = _by_name.get(_k) or _by_lower.get(_k.lower())
    if _p is not None:
        _val = float(_v) if not _p.is_quantized and isinstance(_v, (int, float)) else _v
        _clamped = max(_p.min, min(_p.max, float(_val))) if isinstance(_val, (int, float)) else _val
        _p.value = _clamped
        _applied.append(_p.name)

result = {{
    "track": _t.name,
    "device": _d.name,
    "applied": _applied,
    "count": len(_applied),
}}
"""
    return client.run(code)


def list_parameters(
    client: McpTransport,
    track: str | int,
    device: str | int = 0,
) -> list[dict[str, Any]]:
    """List all parameters of a device with their ranges and current values."""
    t_expr = _track_expr(track)
    d_expr = _device_expr(t_expr, device)

    code = f"""
_t = {t_expr}
_d = {d_expr}
result = [
    {{
        "name": p.name,
        "min": p.min,
        "max": p.max,
        "value": p.value,
        "is_quantized": p.is_quantized,
    }}
    for p in _d.parameters
]
"""
    return client.run(code)
