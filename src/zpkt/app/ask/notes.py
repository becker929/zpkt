"""Project notes: one Markdown file per project in the session's folder (notes/<PROJECT>.md), kept without asking.

Reading: when a message names a project (HW002), its notes go to the agent with that message, once per session and
again whenever the file has changed. Writing: after each agent turn of a session on a project, `write` (a small model
call, given by the caller; without one nothing is written) makes up to four lines worth keeping, added under a date.
A project is a name that already has a notes file, or a word shaped like a set name (letters then three digits).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zpkt.app.ask.events import Event

GEAR = frozenset(
    [
        "TR808",
        "TR909",
        "TR606",
        "TR707",
        "TR727",
        "TB303",
        "SH101",
        "MC202",
        "MC303",
        "MC505",
        "JP8000",
        "DX100",
        "MPC500",
        "SP404",
        "SP303",
        "RE201",
        "RE501",
        "SM57",
        "SM58",
    ]
)
SHAPE = re.compile(r"\b[A-Za-z]{2,5}\d{3}\b")
MAX_READ = 8000
INSTRUCTIONS = (
    "You keep the notes of a music project. Below is one exchange between the producer and an AI agent working on it.\n"
    "Write the lines worth keeping for someone who opens this project next week: decisions made, things measured "
    "(keep the numbers and units exactly as given), files made or changed, and what to do next.\n"
    "At most 4 lines, each under 30 words, plain statements, no praise, nothing that is not in the exchange.\n"
    "If nothing is worth keeping (small talk, a question with no outcome), give an empty list.\n"
    'Answer with JSON only: {"notes": ["...", "..."]}'
)
Writer = Callable[[str], str]  # a prompt -> the model's text


log = logging.getLogger(__name__)


def one_line(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def notes_file(cwd: str, project: str) -> Path:
    return Path(cwd) / "notes" / f"{project}.md"


def known(cwd: str) -> list[str]:
    try:
        return sorted(f.stem for f in (Path(cwd) / "notes").glob("*.md"))
    except OSError:
        return []


def named(text: str, projects: Iterable[str] = ()) -> str | None:
    """The project a message names: known projects win over a new set-shaped name."""
    best: tuple[int, str] | None = None
    for p in projects:
        m = re.search(rf"(^|[^\w]){re.escape(p)}($|[^\w])", text, re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), p)
    if best:
        return best[1]
    for m in SHAPE.finditer(text):
        p = m.group(0).upper()
        if p not in GEAR:
            return p
    return None


def check_notes(text: str) -> list[str]:
    """The checks a model's lines pass before they are written."""
    m = re.search(r"\{[\s\S]*\}", text or "")
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        return []
    lines = [one_line(re.sub(r"^[-*•\s]+", "", n), 300) for n in data["notes"] if isinstance(n, str)]
    return [ln for ln in lines if len(ln) > 3 and not re.search(r"```|</?\w", ln)][:4]


def size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@dataclass
class Context:
    project: str
    n: int  # the notes file's size when read
    text: str  # for the agent; empty when it already has this version
    event: Event | None


@dataclass
class Turn:
    user: str
    answer: str = ""
    tools: int = 0
    touched: list[str] = field(default_factory=list)


class Notes:
    """`save` persists the session index (the store's); `emit(session id, event)` adds an event to a session."""

    def __init__(
        self, emit: Callable[[str, Event], Event], save: Callable[[], None], write: Writer | None = None
    ) -> None:
        self.emit, self.save, self.write = emit, save, write
        self.turns: dict[str, Turn] = {}

    def context(self, s: dict[str, Any], prompt: str) -> Context | None:
        if not s.get("cwd") or s.get("kind") == "self":
            return None
        project = named(prompt, known(s["cwd"]))
        if not project:
            return None
        f, n, rel = notes_file(s["cwd"], project), 0, f"notes/{project}.md"
        n = size(f)
        if (s.get("notesSeen") or {}).get(project) == n:
            return Context(project, n, "", None)
        if not n:
            return Context(
                project,
                n,
                f"Project {project} has no notes yet. The app keeps them in {rel} and adds a dated entry after each turn; "
                "add to that file rather than starting another.",
                None,
            )
        body = f.read_text()
        if len(body) > MAX_READ:
            body = f"…(older notes cut; the whole file is {rel})…\n{body[-MAX_READ:]}"
        text = (
            f"Project notes for {project} (the file {rel}; the app adds a dated entry after each turn, so correct or "
            f"add to that file rather than starting another):\n\n{body.strip()}"
        )
        return Context(project, n, text, {"type": "notes", "status": "loaded", "project": project})

    def seen(self, s: dict[str, Any], c: Context | None) -> None:
        if c is None:
            return
        s["project"] = c.project
        s["notesSeen"] = {**(s.get("notesSeen") or {}), c.project: c.n}
        self.save()
        if c.event:
            self.emit(s["id"], c.event)

    def record(self, s: dict[str, Any], turn: Turn) -> list[str]:
        """Write the turn's lines to the project's notes. Returns the lines written."""
        project = s.get("project")
        if not project or not s.get("cwd") or self.write is None:
            return []
        f = notes_file(s["cwd"], project)
        if any((Path(s["cwd"]) / p).resolve() == f.resolve() for p in turn.touched):
            s["notesSeen"] = {**(s.get("notesSeen") or {}), project: size(f)}  # the agent wrote the notes itself
            self.save()
            return []
        answer = turn.answer.strip()
        if not turn.tools and len(answer) < 200:
            return []
        prompt = (
            f"{INSTRUCTIONS}\n\nProject: {project}\n\nThe producer asked:\n{turn.user[:800]}\n\n"
            f"Files the agent wrote: {', '.join(turn.touched[:12]) or 'none'}\n\nThe agent's answer:\n{answer[:3200]}"
        )
        try:
            lines = check_notes(self.write(prompt))
        except Exception as exc:  # the notes are a courtesy: a failed model call never fails the turn
            log.warning(f"ask: notes: {exc}")
            return []
        if not lines:
            return []
        before = size(f)
        in_sync = (s.get("notesSeen") or {}).get(project) == before
        f.parent.mkdir(parents=True, exist_ok=True)
        if not before:
            f.write_text(
                f"# {project} project notes\n\nKept by the app: a dated entry after each turn that worked on {project}. Edit freely.\n"
            )
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with f.open("a") as fh:
            fh.write(
                f"\n## {stamp}\n\nAsked: {one_line(turn.user, 200)}\n\n" + "\n".join(f"- {ln}" for ln in lines) + "\n"
            )
        if in_sync or not before:
            s["notesSeen"] = {**(s.get("notesSeen") or {}), project: size(f)}
            self.save()
        self.emit(s["id"], {"type": "notes", "status": "saved", "project": project, "lines": lines})
        return lines

    def on_event(self, sid: str, e: Event) -> Turn | None:
        """Follow the events of a session; returns the turn that just ended well, for `record`."""
        if e.get("type") == "prompt":
            if e.get("engine") == "instant" or e.get("auto"):
                self.turns.pop(sid, None)
            else:
                self.turns[sid] = Turn(str(e.get("text", "")))
            return None
        t = self.turns.get(sid)
        if t is None or e.get("parent"):
            return None
        if e.get("type") == "message" and e.get("role") != "user":
            t.answer += str(e.get("content") or "")
        elif e.get("type") == "tool_use":
            t.tools += 1
            t.answer = ""  # only what it said after its last tool call is the answer
            p = e.get("parameters") or {}
            file = p.get("file_path") or p.get("absolute_path") or p.get("path")
            if (
                isinstance(file, str)
                and re.fullmatch(r"(?i)write_file|replace|edit|multiedit|write", str(e.get("tool_name")))
                and file not in t.touched
            ):
                t.touched.append(file)
        elif e.get("type") == "run_end":
            self.turns.pop(sid, None)
            if not e.get("code") and not e.get("signal") and not e.get("error"):
                return t
        return None
