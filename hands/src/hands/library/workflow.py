"""The seven steps of a track, in order. docs/workflow.md says what each means and what "done" is.

Work can happen out of order (mix moves before the arrangement is final), so a track's headline is
its lowest incomplete step: the first step, in this order, below 100 %.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    numeral: str
    name: str
    cap: int  # the most the heuristics give; the rest takes a record (Anthony's word or a documented decision)
    done: str


STEPS: tuple[Step, ...] = (
    Step("collage", "I", "audio collage", 100,
         "found and library sounds chosen, cut, resampled and laid out as the track's bed"),
    Step("drums", "II", "drums", 100,
         "kick, rumble, hats and percussion programmed and placed across the arrangement"),
    Step("arrange", "III", "arrange", 90,
         "a Short-length arrangement (33-50 s) with at least three sections, approved by Anthony"),
    Step("kick", "IV", "kick", 80,
         "the kick and rumble have their own processed chain and Anthony has picked the sound"),
    Step("mix", "V", "mix", 80,
         "groups and buses processed, levels set, a mix render Anthony accepts"),
    Step("master", "VI", "master", 80,
         "a master-bus chain and a mastered export at -14 to -11 LUFS, at most -1.5 dBTP"),
    Step("release", "VII", "release", 60,
         "the final export is published as a YouTube Short and its link is recorded"),
)
KEYS = tuple(s.key for s in STEPS)
BY_KEY = {s.key: s for s in STEPS}

SHORT_S = (33.0, 50.0)       # target length of a Short (docs/hw002, Anthony's 1 Oct feedback)
NEAR_SHORT_S = (25.0, 64.0)  # close enough to cut down or pad out
MASTER_LUFS = (-14.0, -11.0)  # ears/mlab/guides/youtube-short-delivery.md
MASTER_TP = -1.0              # dBTP; the spec says -1.5, -1.0 allows for meter differences


def lowest_incomplete(percents: dict[str, int]) -> str | None:
    """The first step, in workflow order, that is not at 100 %; None when all seven are done."""
    return next((k for k in KEYS if percents.get(k, 0) < 100), None)
