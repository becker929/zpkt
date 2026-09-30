"""Smoke tests for the hands package.

All tests run offline using MockTransport — no Ableton required.
"""

from __future__ import annotations

import json

from hands.models import (
    EQ8Band,
    EQ8Spec,
    Feedback,
    KickConfig,
    MidiNote,
    MidiPattern,
    PercConfig,
    PercGroup,
    ProjectConfig,
    SamplePad,
)
from hands.transport import DryRunTransport, MockTransport


def test_project_config_round_trip() -> None:
    config = ProjectConfig(
        name="Smoke Test",
        tempo=130.0,
        percussion=PercConfig(
            groups=(
                PercGroup(
                    label="hats",
                    samples=(SamplePad(note=36, name="Hat 01"),),
                    main=SamplePad(note=36, name="Hat 01"),
                ),
            ),
            midi=MidiPattern(
                name="hat_pattern",
                length_beats=4.0,
                notes=(MidiNote(pitch=36, time=0.0, duration=0.25, velocity=100),),
            ),
        ),
        kick=KickConfig(
            samples=(SamplePad(note=60, name="Kick 01"),),
            main=SamplePad(note=60, name="Kick 01"),
            midi=MidiPattern(
                name="kick_pattern",
                length_beats=4.0,
                notes=(MidiNote(pitch=60, time=0.0, duration=0.25, velocity=127),),
            ),
        ),
    )
    json_str = config.model_dump_json()
    restored = ProjectConfig.model_validate_json(json_str)
    assert config == restored


def test_feedback_round_trip() -> None:
    fb = Feedback(
        session_id="sess-001",
        render_path="/tmp/render.mp3",
        text="More punch in the kick",
        timestamp_utc="2026-03-26T00:00:00Z",
        rating=4,
    )
    restored = Feedback.model_validate_json(fb.model_dump_json())
    assert restored == fb


def test_mock_transport() -> None:
    from hands.transport import McpResult
    transport = MockTransport(responses=[McpResult(status="ok", result="ok")])
    result = transport.execute("song.tempo = 130.0")
    assert result.status == "ok"
    assert result.result == "ok"
    assert len(transport.calls) == 1
    assert "130.0" in transport.calls[0]


def test_sample_pad_start_constraint() -> None:
    """start must be 0-100 (percentage), not a raw sample frame."""
    pad = SamplePad(note=36, name="test", start=50)
    assert pad.start == 50

    import pytest
    with pytest.raises(Exception):
        SamplePad(note=36, name="test", start=101)


def test_project_config_defaults() -> None:
    config = ProjectConfig(name="Minimal")
    assert config.tempo == 140.0
    assert config.percussion.groups == ()
    assert config.kick.samples == ()
    assert config.rumble.devices == ()


def test_eq8_spec_serialization() -> None:
    eq = EQ8Spec(bands=(
        EQ8Band(band=1, mode=2, freq_hz=80.0, gain=-6.0),
        EQ8Band(band=2, mode=5, freq_hz=8000.0, gain=0.0),
    ))
    data = json.loads(eq.model_dump_json())
    assert len(data["bands"]) == 2
    assert data["bands"][0]["freq_hz"] == 80.0
