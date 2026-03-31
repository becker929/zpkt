"""Tests for hands.vibe — models and tunnel lazy-import. All offline."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from hands.vibe.models import BounceRequest, FeedbackSubmission, VibeSession


def test_bounce_request_round_trip() -> None:
    b = BounceRequest(beats=32, output_path="out.wav")
    restored = BounceRequest.model_validate_json(b.model_dump_json())
    assert restored == b


def test_bounce_request_defaults() -> None:
    b = BounceRequest()
    assert b.beats == 64
    assert b.output_path == "bounce.wav"


def test_bounce_request_beats_zero_raises() -> None:
    with pytest.raises(ValidationError):
        BounceRequest(beats=0)


def test_bounce_request_beats_negative_raises() -> None:
    with pytest.raises(ValidationError):
        BounceRequest(beats=-1)


def test_vibe_session_round_trip() -> None:
    s = VibeSession(
        session_id="sess-42",
        started_at="2026-01-01T00:00:00Z",
        bounces=("a.wav", "b.wav"),
    )
    restored = VibeSession.model_validate_json(s.model_dump_json())
    assert restored == s


def test_vibe_session_empty_bounces() -> None:
    s = VibeSession(session_id="s", started_at="2026-01-01T00:00:00Z")
    assert s.bounces == ()


def test_feedback_submission_round_trip() -> None:
    f = FeedbackSubmission(session_id="s1", text="great", rating=4)
    restored = FeedbackSubmission.model_validate_json(f.model_dump_json())
    assert restored == f


def test_feedback_submission_valid_ratings() -> None:
    for r in range(1, 6):
        FeedbackSubmission(session_id="s", text="t", rating=r)


def test_feedback_submission_rating_zero_raises() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmission(session_id="s", text="t", rating=0)


def test_feedback_submission_rating_six_raises() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmission(session_id="s", text="t", rating=6)


def test_feedback_submission_rating_none_ok() -> None:
    f = FeedbackSubmission(session_id="s", text="t", rating=None)
    assert f.rating is None


def test_feedback_submission_bounce_path_optional() -> None:
    f = FeedbackSubmission(session_id="s", text="t")
    assert f.bounce_path is None


def test_tunnel_imports_without_pyngrok() -> None:
    from hands.vibe.tunnel import close_all_tunnels, open_tunnel
    assert callable(open_tunnel)
    assert callable(close_all_tunnels)


def test_close_all_tunnels_no_op_without_pyngrok() -> None:
    from hands.vibe.tunnel import close_all_tunnels
    close_all_tunnels()
