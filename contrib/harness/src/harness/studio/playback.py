"""What the phone that owns the speaker has still to play.

The mic and the speaker never overlap: the mic is offered only once the owner's phone reports that it has played
(or dropped) every item the Mac sent it. Items are speech streams and `play` commands; the phone counts them back
in `playback` messages, so a message lost in flight can't open the mic early. A phone that never reports is waited
for only as long as what it was sent could take to play.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

SPEECH_MAX_S = 90.0           # no utterance is longer: the latest a phone can still be playing one
PLAYBACK_SLACK_S = 15.0       # on top of an item's own length, before giving up on the phone's "done"


class Playback:
    def __init__(self) -> None:
        self.sent = 0                         # items sent to the owner to play
        self.done = 0                         # ... that it reports finished or dropped
        self._caught_up = asyncio.Event()     # set when the count may have caught up (or there is no owner)
        self._caught_up.set()
        self._deadline = 0.0                  # when everything sent should have played, even if no "done" arrives

    def reset(self) -> None:
        """Nothing is playing any more: audio was stopped, or another phone took the speaker. The phone's count
        restarts too."""
        self.sent = self.done = 0
        self._caught_up.set()

    def item(self, seconds: float | None = None) -> None:
        """One more item for the owner to play; it should be done within `seconds` (plus slack) of now. A speech
        stream's length isn't known when it starts, so it gets the longest an utterance can be."""
        self.sent += 1
        self._caught_up.clear()
        length = SPEECH_MAX_S if seconds is None else seconds
        self._deadline = max(self._deadline, time.monotonic() + length + PLAYBACK_SLACK_S)

    def report(self, done: int, idle: bool) -> None:
        """The owner says it has finished or dropped `done` items, and whether it is playing anything now."""
        self.done = max(self.done, done)
        if self.done >= self.sent and idle:
            self._caught_up.set()

    def owner_left(self) -> None:
        self._caught_up.set()

    async def played(self, has_owner: Callable[[], bool]) -> None:
        """Until the owner has played everything it was sent, it has gone, or it should long have finished."""
        while has_owner() and self.done < self.sent:
            self._caught_up.clear()
            wait = self._deadline - time.monotonic()
            if wait <= 0:
                log.warning("the phone never reported playing %d of %d items; going on", self.sent - self.done,
                            self.sent)
                return
            try:
                await asyncio.wait_for(self._caught_up.wait(), wait)
            except TimeoutError:
                pass
