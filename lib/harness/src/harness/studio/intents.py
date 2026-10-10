"""Spoken commands the app handles itself, without waiting for Claude.

Only a whole utterance that is a command counts: "play again", "loop that three times", "play it twice",
"stop". Anything longer ("play again but with more reverb") goes to Claude, which has the same play_music tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMBERS = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "thrice": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10}
MAX_LOOPS = 16

# Words that carry no meaning in a command: politeness, fillers, the stop word if it slipped through.
FILLER = r"(?:okay|ok|alright|all right|so|um+|uh+|hey|claude|please|can you|could you|would you|just|now|" \
         r"thanks|thank you|tomato|go ahead|and)"
TARGET = r"(?:it|that|this|the music|the track|the loop|the last one|the a ?b|again)"
NUM = r"(?P<n>\d+|" + "|".join(NUMBERS) + r")"

PATTERNS = [
    ("play", re.compile(rf"^(?:play|loop|repeat) {TARGET}(?: {TARGET})? (?:{NUM})(?: times?)?$")),
    ("play", re.compile(rf"^(?:play|loop|repeat)(?: {TARGET})* (?:{NUM})(?: times?)?$")),
    ("play", re.compile(rf"^(?:{NUM}) (?:more )?times?$")),
    ("play", re.compile(rf"^(?:play|loop|repeat) {TARGET}(?: {TARGET})?$")),
    ("play", re.compile(r"^(?:again|one more time|once more|replay|play again|again please)$")),
    ("play", re.compile(r"^(?:play|hear|let me hear) (?:it|that|this) (?:one more time|once more|again)$")),
    ("stop", re.compile(rf"^(?:stop|pause|quiet|silence|enough)(?: {TARGET}| playing| playback| the music)?$")),
]


@dataclass(frozen=True)
class Intent:
    action: str        # "play" or "stop"
    loops: int = 1


def normalise(text: str) -> str:
    t = text.lower().replace("-", " ")
    t = re.sub(r"[^\w\s/]", " ", t)
    t = re.sub(rf"\b{FILLER}\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse(text: str) -> Intent | None:
    t = normalise(text)
    if not t or len(t.split()) > 8:
        return None
    for action, pattern in PATTERNS:
        m = pattern.match(t)
        if not m:
            continue
        if action == "stop":
            return Intent("stop", 0)
        n = m.groupdict().get("n")
        loops = 1 if n is None else (int(n) if n.isdigit() else NUMBERS[n])
        return Intent("play", max(1, min(loops, MAX_LOOPS)))
    return None
