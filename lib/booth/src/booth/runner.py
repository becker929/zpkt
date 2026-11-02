"""One job at a time, and the rule that the booth stops itself on any surprise (docs/bluesky-bot.md).

When may a job start? Only when the booth is open, inside its hours, nothing else used the LOM in the last few
minutes, and **one of the booth's own sets is in front of Live**. That last rule is the lease: Anthony gives the
booth Live by leaving it on booth_template, and takes it back by opening any set of his. The booth never opens a set
over one of his, so it can never close his work or raise "Save changes?" on it.

A Stop (a dialog, the wrong set, a LOM timeout, a bad render) holds the job, closes the booth and sends ntfy. It never
retries a Live step and never takes the next job. `booth open` requeues held jobs once Anthony has looked.
"""

from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime
from typing import Callable

from . import PREFIX
from . import compile as C
from . import measure as M
from . import palette as P
from .check import check
from .config import Settings
from .gui import Stop
from .jobs import Jobs

log = logging.getLogger(__name__)


TARGET_LUFS = -14.0
LOUDNESS_SLACK = 2.0      # within this of the target, the first export stands
MAX_MASTER_GAIN_DB = 24.0  # the Limiter's Input Gain tops out at +24 dB


def loudness_gain(lufs: float | None, current_db: float) -> float | None:
    """The Limiter's Input Gain for a second export when the first came out quiet, else None.

    The first two real renders (2026-11-01) came out at -21.6 and -20.7 LUFS and never reached the limiter: sparse
    pieces can't be balanced by track levels alone. The gain is added in Live, so the render stays Live's own."""
    if lufs is None or lufs >= TARGET_LUFS - LOUDNESS_SLACK:
        return None
    return float(round(min(MAX_MASTER_GAIN_DB, current_db + TARGET_LUFS - lufs)))   # Live shows it in whole dB above 10


class Gate:
    """Is Live the booth's to use now? Each check is a function, so tests can stand in for Live."""

    def __init__(self, settings: Settings, *, front: Callable[[], str | None] | None = None,
                 last_lom: Callable[[], datetime | None] | None = None, now: Callable[[], datetime] = datetime.now) -> None:
        self.settings = settings
        self._front = front
        self._last_lom = last_lom
        self.now = now
        self.ours_until: float = 0.0          # the booth's own LOM use, which last_lom sees too

    def front(self) -> str | None:
        if self._front:
            return self._front()
        from hands.live import ui
        try:
            return ui.front_title()
        except ui.UiError:
            return None

    def last_lom(self) -> datetime | None:
        if self._last_lom:
            return self._last_lom()
        from hands.live import session
        return session.last_lom_connection()

    def reason(self, jobs: Jobs) -> str | None:
        """None when a job may start, else why not (shown to the bot as 503 closed)."""
        if jobs.kv("open", "0") != "1":
            return jobs.kv("reason", "closed") or "closed"
        if not self.settings.in_hours(self.now()):
            return "outside the booth's hours"
        front = self.front()
        if not front or not front.startswith(PREFIX):
            return "Live is being used for something else"
        last = self.last_lom()
        if last and last.timestamp() > self.ours_until + 5 and (self.now() - last).total_seconds() < self.settings.quiet_s:
            return "Live was used by something else in the last few minutes"
        return None


class Runner:
    def __init__(self, jobs: Jobs, settings: Settings, gate: Gate, *, builder: Callable, notify: Callable[[str, str], None],
                 encode: Callable | None = None, loop: Callable | None = None) -> None:
        self.jobs, self.settings, self.gate = jobs, settings, gate
        self.builder = builder                # client -> live.Builder (a fake in tests)
        self.notify = notify
        self.encode = encode or _encode
        self.loop = loop or _loop
        self.current: str | None = None

    def close(self, reason: str) -> None:
        self.jobs.set_kv("open", "0")
        self.jobs.set_kv("reason", reason)

    def open(self) -> int:
        self.jobs.set_kv("open", "1")
        self.jobs.set_kv("reason", "")
        return self.jobs.requeue_held()

    def tick(self) -> str | None:
        """Start the next job if allowed; returns its id once it has finished, else None."""
        if self.gate.reason(self.jobs):
            return None
        job = self.jobs.next()
        if not job:
            return None
        self.current = job["id"]
        try:
            self.run(job)
        finally:
            self.current = None
            self.gate.ours_until = time.time()
        return job["id"]

    def run(self, job: dict) -> None:
        jid = job["id"]
        out = self.jobs.dir / jid
        timings: dict[str, float] = {}
        t0 = time.time()
        self.jobs.update(jid, state="building", stage="compile", started=t0, attempts=(job["attempts"] or 0) + 1)
        stage = {"name": "compile"}

        def step(name: str) -> None:
            stage["name"] = name
            self.jobs.update(jid, stage=name)

        def mark(name: str, since: float) -> float:
            timings[name] = round(time.time() - since, 2)
            self.jobs.update(jid, timings=timings)
            return time.time()

        res = check(job["score"])
        if not res.ok:
            self.jobs.update(jid, state="failed", finished=time.time(), error={
                "stage": "compile", "code": "invalid_score", "message": res.errors[0]["message"], "retryable": False})
            return
        score = res.score
        pal = P.load(score.palette)
        plan = C.compile(score, pal)
        sections, offset = [], 0.0
        for k, sec in enumerate(score.song):
            length = sec.bars * 4 * 60.0 / score.bpm
            sections.append((f"section {k + 1}", offset, offset + length))
            offset += length
        b = self.builder(step)
        try:
            t = time.time()
            front = b.open(jid)
            t = mark("open", t)
            b.build(plan, front)
            t = mark("build", t)
            self.jobs.update(jid, state="rendering")
            wav = b.export(plan, out / f"render-{jid}.wav", front)   # staged by the Save panel first: a unique name
            t = mark("export", t)
            m = M.measure(wav, sections)
            if "silent" in m["flags"]:
                raise Stop("render: silent; Live's audio engine may be off")
            gain = loudness_gain(m["lufs"], plan.master_gain_db)
            if gain is not None:                       # quiet: more into Main's limiter, in Live, and export again
                step("loudness")
                b.master_gain(plan, gain, front)
                wav = b.export(plan, out / f"render-{jid}-2.wav", front)
                m = M.measure(wav, sections)
                m["master_gain_db"] = gain
                t = mark("loudness", t)
            b.close(jid)
            t = mark("close", t)
        except Stop as exc:
            self._hold(jid, stage["name"], str(exc))
            return
        except Exception as exc:          # a bug in the booth, not Live's state: still hold, a person should look
            log.exception("job %s", jid)
            self._hold(jid, stage["name"], f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
            return
        self.jobs.update(jid, state="measuring", stage="encode")
        try:
            m["notes"] = M.explain(m["flags"])
            (out / "measure.json").write_text(__import__("json").dumps(m, indent=2) + "\n")
            self.encode(plan, score, wav, out, self.settings.video_size)
            if (job.get("want") or {}).get("loop"):   # for a Room World room: the song folded into a seamless loop
                self.loop(wav, plan.beats * 60.0 / plan.bpm, out / "loop.m4a")
            mark("encode", t)
        except Exception as exc:
            log.exception("job %s encode", jid)
            self.jobs.update(jid, state="failed", finished=time.time(), error={
                "stage": "encode", "code": "encode_failed", "message": str(exc)[:500], "retryable": True})
            return
        timings["total"] = round(time.time() - t0, 2)
        self.jobs.update(jid, state="done", stage="", finished=time.time(), timings=timings, measure=m)

    def _hold(self, jid: str, stage: str, message: str) -> None:
        self.jobs.update(jid, state="held", finished=time.time(), error={
            "stage": stage, "code": "held", "message": message[:1000], "retryable": True})
        self.close(f"held at {stage}")
        log.error("held %s at %s: %s", jid, stage, message)
        self.notify("booth held a job", f"{jid} at {stage}: {message[:300]}\nLook at Live, then `booth open`.")


def _loop(wav, seconds, m4a) -> None:
    from . import video
    video.loop(wav, seconds, m4a)


def _encode(plan, score, wav, out, size) -> None:
    from . import video
    seconds = plan.render_beats * 60.0 / plan.bpm
    geom = video.roll(plan, score.title, f"{score.bpm:g} BPM · {score.key}".rstrip(" ·"), size, out / "still.jpg")
    video.encode(wav, out / "still.jpg", geom, size, seconds, out / "render.m4a", out / "video.mp4")
