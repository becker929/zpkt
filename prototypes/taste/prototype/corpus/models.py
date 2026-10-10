"""Pydantic schema for the taste corpus (Scaling Taste §3.3)."""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Decomposition(str, Enum):
    full_mix = "full_mix"
    # stem:<name> e.g. "stem:kick", "stem:bass"
    # band:<range> e.g. "band:sub", "band:low"


class EvaluationLens(str, Enum):
    sound_design = "sound_design"
    groove = "groove"
    mix_balance = "mix_balance"
    arrangement = "arrangement"
    tension = "tension"
    overall = "overall"


class SourceTag(str, Enum):
    manual = "manual"           # producer hand-labeled
    model = "model"             # taste model auto-labeled
    correction = "correction"   # producer corrected a model judgment


class AnnotationEntry(BaseModel):
    clip_id: str
    source_track: str
    time_range: tuple[float, float]              # (start_sec, end_sec)
    decomposition: str = "full_mix"             # Decomposition value or "stem:X" / "band:X"
    evaluation_lens: EvaluationLens = EvaluationLens.overall
    verdict: int = Field(..., ge=1, le=5)        # 1=delete, 3=functional, 5=would play out
    what_works: str = ""
    what_fails: str = ""
    comparison_anchors: str = ""                 # "better than X because Y"
    # 512-dim DCLAP embedding (stored as list)
    embedding: list[float] = Field(default_factory=list)
    # Metadata
    timestamp: float = Field(default_factory=time.time)
    source_tag: SourceTag = SourceTag.manual
    corrects: Optional[str] = None               # clip_id of the entry this corrects
    # Extra notes (used by CLI 'corpus add')
    notes: str = ""

    class Config:
        use_enum_values = True


class AnnotationUpdate(BaseModel):
    """Partial update applied to an existing entry (used in correction mode)."""
    verdict: Optional[int] = Field(None, ge=1, le=5)
    what_works: Optional[str] = None
    what_fails: Optional[str] = None
    comparison_anchors: Optional[str] = None
    notes: Optional[str] = None
