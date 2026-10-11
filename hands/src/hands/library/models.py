"""The inventory as data: `hands library inventory --json`. Source of lib/contracts/inventory.schema.json."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StepKey = Literal["collage", "drums", "arrange", "kick", "mix", "master", "release"]


class Record(BaseModel):
    """A step's state on someone's word. It beats the heuristic."""
    model_config = ConfigDict(extra="forbid")

    percent: int = Field(ge=0, le=100)
    by: Literal["anthony", "docs", "agent"] = Field(
        "anthony", description="anthony: his word; docs: a decision recorded in zpkt docs; agent: an agent's judgment")
    note: str = ""
    source: str = Field("", description="where it is written down, e.g. docs/hw002/batch-6-7-decisions.md")
    date: str = Field("", description="YYYY-MM-DD")
    url: str = Field("", description="release: the published link")


class StepScore(BaseModel):
    step: StepKey
    numeral: str
    percent: int = Field(ge=0, le=100, description="the record's percent if there is one, else the heuristic's")
    heuristic: int = Field(ge=0, le=100)
    record: Record | None = None
    evidence: list[str] = Field(default_factory=list)


class TrackReport(BaseModel):
    track: str
    folder: str | None = Field(None, description="the project folder, absolute")
    set: str | None = Field(None, description="the newest Live set, whose facts score the steps")
    sets: int = 0
    last_saved: str | None = Field(None, description="the newest set's modification date, YYYY-MM-DD")
    lowest_incomplete: StepKey | None = Field(None, description="the first step, in workflow order, below 100 %")
    overall: int = Field(0, ge=0, le=100, description="mean of the seven percents")
    steps: list[StepScore]
    notes: list[str] = Field(default_factory=list)


class Inventory(BaseModel):
    generated: str = Field(description="ISO 8601 time of the scan")
    roots: list[str]
    tracks: list[TrackReport]
    skipped: list[str] = Field(default_factory=list, description="folders and sets that were not scored, and why")
