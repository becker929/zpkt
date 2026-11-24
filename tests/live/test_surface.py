"""Tests for zpkt.live.surface translation of zpkt-surface JSON values."""

from zpkt.live import surface


def test_map_surface_values():
    surface_values = {
        "cutoff": 3800,
        "resonance": 18,
        "decay": 180,
        "spread": 65,
        "detune": 14,
        "drive": 4,
        "level": -0.5,
        "ab": "b",
    }

    mapped = surface.map_surface_values(surface_values)
    assert "Filter Freq" in mapped
    assert 0.70 < mapped["Filter Freq"] < 0.82
    assert "Filter Res" in mapped
    assert 0.20 < mapped["Filter Res"] < 0.25
    assert "Ae Decay" in mapped
    assert 0.45 < mapped["Ae Decay"] < 0.55
    assert mapped["Spread"] == 65.0
    assert mapped["B Fine"] == 14.0
    assert mapped["C Fine"] == 28.0
    assert mapped["Filter Drive"] == 4.0


def test_map_surface_values_custom_override():
    values = {"my_knob": 42}
    custom = {"my_knob": "Filter Freq"}
    mapped = surface.map_surface_values(values, custom)
    assert mapped["Filter Freq"] == 42
