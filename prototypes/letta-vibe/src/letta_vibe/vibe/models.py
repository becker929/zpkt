"""Pydantic models for the vibe feedback loop."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

_FROZEN: dict[str, Any] = {"frozen": True}


class BounceRequest(BaseModel):
    """Request to bounce audio from Ableton."""
    model_config = _FROZEN  # type: ignore[assignment]
    beats: int = Field(default=64, gt=0)
    output_path: str = "bounce.wav"


class VibeSession(BaseModel):
    """An active vibe session with its metadata."""
    model_config = _FROZEN  # type: ignore[assignment]
    session_id: str
    started_at: str
    bounces: tuple[str, ...] = ()


class FeedbackSubmission(BaseModel):
    """A feedback submission from the phone UI."""
    model_config = _FROZEN  # type: ignore[assignment]
    session_id: str
    text: str
    rating: int | None = Field(default=None, ge=1, le=5)
    bounce_path: str | None = None
