"""The Options service: the one store of Options. It holds the render queue's worker, the folders of older Options,
what agents propose, and what is shown on the Hear bar.

A request for an Option (`make`) is filed on the queue (zpkt.app.renderqueue) and rendered one Version at a time:
the Version's values are written to the mix, Live exports the arrangement through zpkt.live.export (the app's one
connection is handed in and held for that Version only), the values go back, and the WAV goes to zpkt.audio.measure.
Each step is streamed to the shell ("rendering 2 of 3"). Live is held per Version, never for the whole job, so a move
from you waits at most one render and is then answered "Live is busy" if it waited too long; it is not dropped.

What an agent proposes is kept here too (zpkt.app.proposals: a record, not a render) and listed with the rest. You
pick any Option with one command, `options.pick`, which puts it on Now.

Mix 2, the spectral fixes, the kick options and panel grids are rendered by their own tools. They are read here (never
changed) and listed as Options, so the old pages keep working on the same files. The export and the measurement are
handed in, so tests render with fakes.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from zpkt.app import options as O
from zpkt.app.bus import Refused
from zpkt.app.connections import LiveConnections
from zpkt.app.proposals import OptionStore
from zpkt.app.renderqueue import RenderQueue
from zpkt.audio.measure import Measure, measure_wav
from zpkt.live import config
from zpkt.live.changes import Who

if TYPE_CHECKING:
    from zpkt.app.desk import Desk

Exporter = Callable[[LiveConnections, Path, float | None, float | None], Path]
Measurer = Callable[[Path], Measure]

CLAIM_WAIT_S = 30.0  # how long a Version waits for Live before the job fails
SETTLE_S = 0.4  # after writing values, before the export starts
JOB_PREFIX = "o"


def export_main(conn: LiveConnections, out: Path, start_beat: float | None, length_beats: float | None) -> Path:
    """Render Main through Live's Export dialog (zpkt.live.export) with the app's connection; the WAV's path."""
    from zpkt.live import export

    files = export.export(conn, out, start_beat, length_beats, method="keys")
    if not files:
        raise RuntimeError("Live exported nothing. Look at Live's window, then render again.")
    return files[0]


def _mtime(path: str | None) -> float | None:
    """When a file last changed; None for no file."""
    try:
        return Path(path).stat().st_mtime if path else None
    except OSError:
        return None


def arranger_dir() -> Path:
    """The arranger's data folder: ARRANGER_DATA (as its scripts read it) or ZPKT_ARRANGER_DIR, read now, else the
    rig's `arranger_dir`."""
    env = os.environ.get("ARRANGER_DATA") or os.environ.get("ZPKT_ARRANGER_DIR")
    return Path(env).expanduser() if env else config.rig().arranger_dir


class Options:
    """The Options of one desk. The queue's files and the measures it keeps live in `folder`."""

    def __init__(
        self,
        desk: Desk,
        exporter: Exporter = export_main,
        measurer: Measurer = measure_wav,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        s = desk.settings
        self.desk, self.exporter, self.measurer, self.pause = desk, exporter, measurer, pause
        self.folder = s.options_dir or config.rig().data_dir / "options"
        self.arranger = s.arranger_dir or arranger_dir()
        self.panels = s.panels_dir or config.rig().renders_dir
        self.queue = RenderQueue(self.folder / "jobs")
        self.proposals = OptionStore(self.folder)  # what agents propose; Ask keeps the file in its own folder
        self.skipped: list[str] = []  # files of older tools that could not be read, said in the list
        self._shown: tuple[str, str] | None = None
        self._lock = threading.Lock()  # the measures and picks files, and the worker's start
        self._running = threading.Lock()  # held by the one run of the queue

    # ---- the small files this service keeps ------------------------------------------------------------------------
    def _read_json(self, name: str) -> dict[str, Any]:
        try:
            data = json.loads((self.folder / name).read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_json(self, name: str, data: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.folder / name)

    def _measure_cached(self, path: Path) -> Measure:
        """The measure of a file, kept until the file changes (measuring a long render takes seconds)."""
        stamp = path.stat().st_mtime
        with self._lock:
            kept = self._read_json("measures.json").get(str(path))
        if kept and kept["mtime"] == stamp:
            return cast(Measure, kept["measure"])
        m = self.measurer(path)
        with self._lock:
            data = self._read_json("measures.json")
            data[str(path)] = {"mtime": stamp, "measure": m}
            self._write_json("measures.json", data)
        return m

    # ---- reading the Options ---------------------------------------------------------------------------------------
    def _imported(self) -> list[O.Option]:
        found: list[O.Option] = []
        self.skipped = []
        mix2 = RenderQueue(self.arranger / "mix2" / "requests")
        found += [O.from_mix2(row, self.arranger / "mix2") for row in mix2.rows() if row.get("id")]
        for name, build, folder in (
            ("renders.json", O.from_spectral, self.arranger / "spectral"),
            ("renders.json", O.from_kick, self.arranger / "kickfuzz"),
        ):
            f = folder / name
            if f.is_file():
                try:
                    found.append(build(json.loads(f.read_text()), folder, f.stat().st_mtime))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.skipped.append(f"{f}: {str(exc)[:80]}")
        for f in sorted(self.panels.glob("*.panel.json")) if self.panels.is_dir() else []:
            try:
                found += O.from_panel(f.name[: -len(".panel.json")], json.loads(f.read_text()), f.stat().st_mtime)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.skipped.append(f"{f}: {str(exc)[:80]}")
        return found

    def _finish(self, option: O.Option, picks: dict[str, Any], measures: dict[str, Any]) -> O.Option:
        """Add what this service knows to an Option: measures kept, the gaps, the Version made Now."""
        versions = []
        for v in option["versions"]:
            kept = measures.get(v["file"] or "")
            if v["measure"] is None and kept and kept["mtime"] == _mtime(v["file"]):
                v = {**v, "measure": kept["measure"]}
            versions.append(v)
        out = O.with_gaps({**option, "versions": versions})
        return {**out, "now": picks.get(out["id"], out["now"])}

    def all(self) -> list[O.Option]:
        """Every Option: the app's own jobs and the older tools', running ones first, then newest first."""
        with self._lock:
            picks, measures = self._read_json("picks.json"), self._read_json("measures.json")
        own = [cast(O.Option, row) for row in self.queue.rows() if row.get("kind") in O.RENDERED_KINDS]
        proposed = [O.from_proposal(p) for p in self.proposals.all() if p.get("id")]
        return O.ordered([self._finish(o, picks, measures) for o in [*own, *self._imported()]] + proposed)

    def get(self, option_id: str) -> O.Option:
        for o in self.all():
            if o["id"] == option_id:
                return o
        raise O.BadOption(f"there is no Option {option_id!r}; list them with options.list")

    def file_of(self, option_id: str, vid: str) -> Path | None:
        """The audio file of a Version, only ever one that an Option names."""
        v = O.find_version(self.get(option_id), vid)
        return Path(v["file"]) if v["file"] else None

    # ---- what the Hear bar shows -----------------------------------------------------------------------------------
    def show(self, option_id: str, vid: str, measure: bool = True) -> dict[str, Any]:
        """Put a Version on the Hear bar: its numbers (measured now if they are not yet) and its gap to the base."""
        option = self.get(option_id)
        v = O.find_version(option, vid)
        if measure and v["measure"] is None and v["file"]:
            self._measure_cached(Path(v["file"]))
            v = O.find_version(self.get(option_id), vid)
        self._shown = (option_id, vid)
        self.desk.push_app(self.message())
        return {"option": option_id, "version": v}

    def message(self) -> dict[str, Any]:
        """{"t": "options"}: every Option and the Version shown, for the shell."""
        shown = None
        if self._shown:
            with contextlib.suppress(O.BadOption):
                option = self.get(self._shown[0])
                shown = {
                    "option": option["id"],
                    "title": option["title"],
                    "version": O.find_version(option, self._shown[1]),
                }
        return {"t": "options", "options": self.all(), "shown": shown, "skipped": list(self.skipped)}

    def push(self, option_id: str) -> None:
        """One Option changed (a job's progress): the shell gets it alone."""
        row = self.queue.get(option_id)
        if row:
            self.desk.push_app({"t": "option", "option": self.get(option_id)})

    # ---- making and rendering --------------------------------------------------------------------------------------
    def make(self, body: dict[str, Any]) -> O.Option:
        """Queue an Option from a request (see options.new_job) and start the worker. Keys must be ones the desk knows."""
        job = O.new_job(body)
        unknown = [k for k in O.keys_of(job) if self.desk.history.value(k) is None]
        if unknown:
            raise O.BadOption(
                f"the desk does not know {', '.join(unknown[:4])}; use state keys of a page the desk has loaded"
            )
        row = self.queue.add(job, prefix=JOB_PREFIX)
        self.start_worker()
        self.push(row["id"])
        return self.get(row["id"])

    def start_worker(self) -> None:
        """Render the queue in a thread of its own. Only one runs at a time (`run_pending` says no to a second), so
        it is safe to start one for every job; each ends when the queue is empty."""
        threading.Thread(target=self.run_pending, daemon=True, name="options-worker").start()

    def _next_job(self) -> str | None:
        for path in self.queue.queued():
            if (self.queue.get(path.stem) or {}).get("kind") in O.RENDERED_KINDS:
                return path.stem
        return None

    def run_pending(self) -> int:
        """Render the queued jobs of this app, oldest first, and return how many it took (0 when another run is
        already at it). A job that fails is marked failed with the reason; the next one still runs."""
        taken = 0
        while self._running.acquire(blocking=False):
            try:
                job_id = self._next_job()
                if job_id is not None:
                    taken += 1
                    try:
                        self._render_job(job_id)
                    except Exception as exc:
                        self._fail(job_id, str(exc) or type(exc).__name__)
            finally:
                self._running.release()
            if job_id is None and self._next_job() is None:  # looked again after letting go: a job may have come in
                break
        return taken

    def _fail(self, job_id: str, reason: str) -> None:
        row = self.queue.get(job_id) or {}
        versions = [
            {**v, "status": "failed", "error": reason} if v["status"] in ("queued", "rendering") else v
            for v in row.get("versions", [])
        ]
        self.queue.update(job_id, status="failed", error=reason, progress=reason, versions=versions)
        self.push(job_id)

    def _set_version(self, job_id: str, vid: str, **fields: Any) -> dict[str, Any]:
        row = self.queue.get(job_id) or {}
        versions = [{**v, **fields} if v["id"] == vid else v for v in row["versions"]]
        done = sum(1 for v in versions if v["status"] == "ready")
        option = O.with_gaps(cast(O.Option, {**row, "versions": versions}))
        return self.queue.update(job_id, versions=option["versions"], done=done)

    def _render_job(self, job_id: str) -> None:
        row = self.queue.get(job_id)
        if row is None:
            return
        guard = self.desk.bus.guard
        if guard is not None:
            try:
                with self.desk.conn.exclusive(wait_s=CLAIM_WAIT_S):  # asking Live which set is open is a call too
                    guard.check()
            except Refused as exc:
                raise RuntimeError(str(exc)) from None
        total = len(row["versions"])
        self.queue.update(
            job_id, status="rendering", started=time.time(), progress=O.progress_text("rendering", 0, total)
        )
        self.push(job_id)
        for i, v in enumerate(list(row["versions"])):
            self.queue.update(job_id, progress=O.progress_text("rendering", i, total))
            self._set_version(job_id, v["id"], status="rendering")
            self.push(job_id)
            try:
                path = self._render_version(job_id, row, v)
                measured = self.measurer(path)
            except Exception as exc:
                self._set_version(job_id, v["id"], status="failed", error=str(exc))
                raise
            self._set_version(job_id, v["id"], status="ready", file=str(path), measure=measured)
            self.push(job_id)
        self.queue.update(job_id, status="ready", finished=time.time(), progress="ready")
        self.push(job_id)

    def _render_version(self, job_id: str, row: dict[str, Any], version: dict[str, Any]) -> Path:
        """Write the Version's values, export, put the values back (whatever happens), and return the WAV."""
        out = self.folder / "renders" / job_id / f"{version['id']}.wav"
        span = row.get("range") or {}
        writes: list[list[Any]] = version.get("writes") or []
        history = self.desk.history
        with self.desk.conn.exclusive(wait_s=CLAIM_WAIT_S):
            before = [[key, (history.value(key) or [None, None])[1]] for key, _ in writes]
            if writes:
                self._put(writes)
            try:
                self.pause(SETTLE_S)
                return self.exporter(self.desk.conn, out, span.get("start_beat"), span.get("length_beats"))
            finally:
                if writes:
                    self._put(before)

    def _put(self, pairs: list[list[Any]]) -> None:
        """Values into Live as the desk's own writes: their echo is not a move of yours, so history does not take it."""
        self.desk.history.expect_writes(pairs)
        self.desk.write(pairs)

    # ---- what agents propose ---------------------------------------------------------------------------------------
    def keep_proposals_in(self, folder: Path) -> None:
        """Keep the proposals' file (options.json) in `folder`: Ask's data folder, where the file has always been."""
        self.proposals = OptionStore(folder)

    def propose(self, data: Any, made_by: Who, session: str | None = None) -> dict[str, Any]:
        """File a proposal (ValueError says what is wrong with it) and show it in the shell. Nothing moves."""
        proposal = dict(self.proposals.propose(data, made_by, session))
        self.desk.push_app(self.message())
        return proposal

    def proposal(self, option_id: str) -> dict[str, Any] | None:
        """The proposal with this id as it is on file, or None when the Option is not a proposal."""
        return next((dict(p) for p in self.proposals.all() if p.get("id") == option_id), None)

    def is_picked(self, option_id: str) -> bool:
        """Did you pick this proposal? Only that lets an agent's move name it (the bus's agent rule)."""
        return self.proposals.is_picked(option_id)

    # ---- Now -------------------------------------------------------------------------------------------------------
    def keep_now(self, option_id: str, vid: str, who: str = "you") -> None:
        """Remember which Version of an Option was made Now. A proposal becomes "picked", and only by you: an
        agent that uses one Option you picked does not pick another for itself."""
        if self.proposal(option_id) is not None:
            if who == "you":
                self.proposals.pick(option_id)
            return
        with self._lock:
            picks = self._read_json("picks.json")
            picks[option_id] = vid
            self._write_json("picks.json", picks)
