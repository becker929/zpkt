"""Top-level Pydantic models for the taste layer.

Verdict is the primary output — serialised to JSON for cross-repo consumption.
No imports from hands or ears.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Verdict(BaseModel):
    """Taste judge output for a single render.

    Produced by the taste judge and consumed by the taste loop orchestrator
    (and optionally by hands for acting on suggestions).
    """

    clip_id: str
    score: int = Field(ge=1, le=5)
    rationale: str
    suggestions: list[str] = Field(default_factory=list)
    retrieved_ids: list[str] = Field(default_factory=list)
    model: str = "unknown"


class FeedbackTuple(BaseModel):
    """One complete feedback cycle — the atomic unit of taste training data.

    Accumulates in the corpus and becomes RAG context for future judgments.
    """

    session_id: str
    render_path: str
    profile_json: str
    verdict: Verdict
    human_feedback: str
    parameter_changes: dict[str, float] = Field(default_factory=dict)
    perceptual_delta: float | None = None
