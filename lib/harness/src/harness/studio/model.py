"""What the chat is made of: messages and their kinds, whose turn it is, and what each phone asked for."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Kind(StrEnum):
    USER = "user"            # what Anthony said, or typed
    AGENT = "agent"          # what Claude said, or a narration of what it is doing
    MUSIC = "music"          # a render to listen to
    SHOTS = "shots"          # a screenshot pair: the full screen and a zoom
    ACTIVITY = "activity"    # one tool call
    NOTICE = "notice"        # the app itself speaking up


class Phase(StrEnum):
    IDLE = "idle"              # hands-free is off, or no phone owns the mic
    LISTENING = "listening"    # the mic is Anthony's
    WORKING = "working"        # Claude has the turn
    RESPONDING = "responding"  # Claude is done; the phone is still playing its answer


class ShotLevel(IntEnum):
    """Ordered: a phone that asked for MINOR also gets MAJOR."""

    NONE = 0
    MAJOR = 1
    MINOR = 2
    FIREHOSE = 3

    @classmethod
    def parse(cls, value: Any, default: "ShotLevel" = None) -> "ShotLevel":
        try:
            return cls[str(value).upper()]
        except KeyError:
            return default if default is not None else cls.MAJOR

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Prefs:
    autoplay: bool = True
    shots: ShotLevel = ShotLevel.MAJOR
    handsfree: bool = True

    @classmethod
    def parse(cls, raw: Any) -> "Prefs":
        raw = raw if isinstance(raw, dict) else {}
        return cls(autoplay=bool(raw.get("autoplay", True)),
                   shots=ShotLevel.parse(raw.get("shots", "major")),
                   handsfree=bool(raw.get("handsfree", True)))

    def wire(self) -> dict[str, Any]:
        return {"autoplay": self.autoplay, "shots": self.shots.label, "handsfree": self.handsfree}


@dataclass
class Message:
    kind: Kind
    data: dict[str, Any]
    turn: str | None = None
    conversation: str = ""
    seq: int = 0            # the store assigns it: the message's id and its place in the chat
    created: float = field(default_factory=time.time)
    rev: int = 0            # grows with every update

    def wire(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind.value, "created": round(self.created, 3), "turn": self.turn,
                "rev": self.rev, "data": self.data}


@dataclass(frozen=True)
class MediaRef:
    """A stored file, served immutable at `url`."""

    url: str
    type: str
    bytes: int
    extra: tuple[tuple[str, Any], ...] = ()

    def wire(self) -> dict[str, Any]:
        return {"url": self.url, "type": self.type, "bytes": self.bytes, **dict(self.extra)}
