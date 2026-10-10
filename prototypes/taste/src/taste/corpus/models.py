"""Pydantic models for corpus annotations and evaluation lenses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnnotationEntry(BaseModel):
    """One annotated render stored in the corpus."""

    clip_id: str
    render_path: str
    profile_json: str
    verdict_json: str
    human_feedback: str = ""
    score: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""


class EvaluationLens(BaseModel):
    """A named dimension for evaluating a render (e.g. 'kick punch', 'mix clarity')."""

    name: str
    description: str
    weight: float = Field(default=1.0, gt=0.0)
