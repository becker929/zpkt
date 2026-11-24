"""Bridge zpkt-surface JSON state into Ableton Live parameter updates."""

from __future__ import annotations

import math
from typing import Any

from hands.live.transport import McpTransport


def hz_to_norm(hz: float) -> float:
    """Map Hz (20..20000) to normalized 0..1 log curve."""
    hz = max(20.0, min(20000.0, float(hz)))
    return (math.log10(hz) - math.log10(20.0)) / (math.log10(20000.0) - math.log10(20.0))


def ms_to_norm_decay(ms: float) -> float:
    """Map decay ms (5..5000) to Operator envelope decay normalized 0..1."""
    ms = max(5.0, min(5000.0, float(ms)))
    # 27ms ~ 0.3, 81ms ~ 0.4, 245ms ~ 0.5
    # log10(ms): log10(27)=1.43, log10(245)=2.39 -> slope ~ 0.207 per decade
    return max(0.0, min(1.0, 0.4 + (math.log10(ms) - math.log10(81.5)) * 0.21))


def map_surface_values(
    values: dict[str, Any],
    custom_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Translate zpkt-surface control values to DAW device parameter values."""
    params: dict[str, Any] = {}
    custom_map = custom_map or {}

    for k, v in values.items():
        if k in ("ab", "abSide"):
            continue

        target = custom_map.get(k)
        if target:
            params[target] = v
            continue

        kl = k.lower()
        if "cutoff" in kl or "filter_freq" in kl:
            val = float(v)
            norm = hz_to_norm(val) if val > 20.0 else val
            params["Filter Freq"] = norm
        elif "resonance" in kl or "filter_res" in kl:
            val = float(v)
            params["Filter Res"] = (val / 100.0) * 1.25 if val > 1.25 else val
        elif "decay" in kl:
            val = float(v)
            norm = ms_to_norm_decay(val) if val > 1.0 else val
            params["Ae Decay"] = norm
            params["Be Decay"] = norm
            params["Ce Decay"] = norm
            params["De Decay"] = norm
        elif "spread" in kl:
            params["Spread"] = float(v)
        elif "detune" in kl:
            val = float(v)
            params["B Fine"] = val
            params["C Fine"] = val * 2.0
        elif "drive" in kl:
            params["Filter Drive"] = float(v)
        elif "level" in kl or "volume" in kl:
            params["Volume"] = float(v)

    return params


def apply_surface_state(
    client: McpTransport,
    state: dict[str, Any],
    track: str | int = 0,
    device: str | int = 0,
    mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply a zpkt-surface state dictionary to Live device parameters in one atomic call."""
    values = state.get("values", state)
    param_updates = map_surface_values(values, mapping)

    t_expr = (
        f"song.tracks[{track}]"
        if isinstance(track, int) or (isinstance(track, str) and track.isdigit())
        else f"next(x for x in song.tracks if x.name == {track!r})"
    )
    d_expr = (
        f"{t_expr}.devices[{device}]"
        if isinstance(device, int) or (isinstance(device, str) and device.isdigit())
        else f"next(d for d in {t_expr}.devices if d.name == {device!r})"
    )

    # Check if level/volume should also adjust mixer
    level_val = values.get("level")

    code = f"""
_t = {t_expr}
_d = {d_expr}
_by_name = {{p.name: p for p in _d.parameters}}
_by_lower = {{p.name.lower(): p for p in _d.parameters}}
_applied = []

for _k, _v in {param_updates!r}.items():
    _p = _by_name.get(_k) or _by_lower.get(_k.lower())
    if _p is not None:
        _val = float(_v) if not _p.is_quantized and isinstance(_v, (int, float)) else _v
        _clamped = max(_p.min, min(_p.max, float(_val))) if isinstance(_val, (int, float)) else _val
        _p.value = _clamped
        _applied.append(_p.name)

# If level is in dB, apply to mixer device
_lvl = {level_val!r}
if _lvl is not None and isinstance(_lvl, (int, float)):
    # 0 dB ~ 0.85 in Live mixer volume
    import math
    _db = float(_lvl)
    _vol = min(1.0, max(0.0, 0.85 * (10.0 ** (_db / 20.0))))
    _t.mixer_device.volume.value = _vol

result = {{
    "track": _t.name,
    "device": _d.name,
    "applied": _applied,
    "count": len(_applied),
}}
"""
    return client.run(code)
