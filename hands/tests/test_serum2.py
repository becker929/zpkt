"""Serum 2 state codec: round trip, preset conversion, mod slots (no plug-in needed)."""
import pytest

cbor2 = pytest.importorskip("cbor2")
pytest.importorskip("zstandard")

from hands.serum2 import state as st  # noqa: E402


def _blob(data, **header):
    return st.encode(st.XferBlob({"component": "processor", "product": "Serum2", **header}, 2, data))


def test_round_trip_and_hash():
    raw = _blob({"Global0": {"plainParams": {"kParamMasterVolume": 0.5}}})
    b = st.decode(raw)
    assert b.data["Global0"]["plainParams"]["kParamMasterVolume"] == 0.5
    assert st.encode(b) == raw  # same data -> same bytes, hash recomputed identically
    import hashlib
    comp_start = raw.index(b"\x28\xb5\x2f\xfd")
    assert b.header["hash"] == hashlib.md5(raw[comp_start:]).hexdigest()


def test_preset_to_processor_drops_preset_fields():
    preset = _blob({"Osc": [1], "presetName": "X", "tags": ["a"], "version": 9.0}, fileType="SerumPreset")
    template = _blob({"version": 11.0, "product": "Serum2"})
    out = st.decode(st.preset_to_processor(preset, template))
    assert "presetName" not in out.data and "tags" not in out.data
    assert out.data["version"] == 11.0 and out.data["Osc"] == [1]
    assert "fileType" not in out.header


def test_mod_slot_shape():
    s = st.mod_slot("env2", "Oscillator", "kParamCoarsePit", 7, 24)
    assert s["source"] == [3, 0] and s["plainParams"] == {"kParamAmount": 24.0}
    assert st.MOD_SOURCES["lfo1"] == 6 and st.MOD_SOURCES["macro1"] == 25
