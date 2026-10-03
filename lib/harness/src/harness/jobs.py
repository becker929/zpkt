"""Claude Code jobs: queued, run one at a time, kept on disk.

A job is one Agent SDK session in the same working directory as the desktop
sessions (~/Desktop), so it loads the same CLAUDE.md files and the same
auto-memory. Each job keeps:

    <jobs_dir>/<id>/job.json      status, prompt, session id, result, cost
    <jobs_dir>/<id>/events.jsonl  what the agent said and which tools it used

The session id lets anyone pick the job up later:
`cd ~/Desktop && claude --resume <session_id>`.

Jobs run one at a time because they share one Live instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .config import Config, secret

log = logging.getLogger(__name__)

# The tools a desktop session uses for this project. Anything else is denied:
# there is nobody at the keyboard to approve it.
JOB_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit",
             "WebFetch", "WebSearch", "TodoWrite", "Task"]
ASK_TOOLS = ["Read", "Glob", "Grep"]

APPEND = """\
You are running as a background job on Anthony's Mac, started from the
browser through the zpkt harness (zpkt/lib/harness). Nobody is watching this
session live: do not ask questions, make reasonable choices and say what you
chose in your final message. The harness sends Anthony a phone notification
when you start and another with your final message when you finish, so end
with a short plain summary (what changed, links, anything he must do).
Follow the memory and the repos' rules as a desktop session would (saving
means branch, push, PR, merge; secrets stay in the Keychain)."""

ASK_APPEND = """\
You are answering a question Anthony asked from the browser, synchronously.
Answer in under 150 words, plain text, no markdown tables. Read files if you
need to; do not change anything."""

TERMINAL = {"done", "failed", "cancelled"}
NOT_SIGNED_IN = ("Claude Code is not signed in for background jobs. On the Mac run `claude setup-token`, "
                 "then store it: security add-generic-password -U -s zpkt-claude-oauth -a \"$USER\" -w")


def explain(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return NOT_SIGNED_IN if "Not logged in" in text else text[:2000]


@dataclass
class Job:
    id: str
    kind: str
    title: str
    prompt: str
    status: str = "queued"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    session_id: str | None = None
    result: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    turns: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("prompt")
        if d["result"] and len(d["result"]) > 4000:
            d["result"] = d["result"][:4000] + "…"
        return d


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _env(cfg: Config) -> dict[str, str]:
    env = dict(cfg.extra_env)
    token = secret("oauth")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def options(cfg: Config, *, ask: bool = False) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(cfg.workdir),
        cli_path=cfg.cli_path,
        model=cfg.model,
        allowed_tools=ASK_TOOLS if ask else JOB_TOOLS,
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit"] if ask else [],
        permission_mode="default" if ask else "acceptEdits",
        system_prompt={"type": "preset", "preset": "claude_code", "append": ASK_APPEND if ask else APPEND},
        setting_sources=["user", "project", "local"],
        max_turns=cfg.ask_turns if ask else cfg.job_turns,
        env=_env(cfg),
    )


def _event(msg: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock) and block.text.strip():
                out.append({"t": time.time(), "text": block.text[:2000]})
            elif isinstance(block, ToolUseBlock):
                summary = json.dumps(block.input)[:300]
                out.append({"t": time.time(), "tool": block.name, "input": summary})
    return out


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, job_id: str) -> Path:
        if not job_id or "/" in job_id or job_id.startswith("."):
            raise ValueError("bad job id")
        return self.root / job_id

    def save(self, job: Job) -> None:
        p = self.path(job.id)
        p.mkdir(exist_ok=True)
        tmp = p / "job.json.tmp"
        tmp.write_text(json.dumps(asdict(job), indent=2))
        tmp.replace(p / "job.json")

    def load(self, job_id: str) -> Job | None:
        f = self.path(job_id) / "job.json"
        return Job(**json.loads(f.read_text())) if f.exists() else None

    def append(self, job_id: str, events: list[dict[str, Any]]) -> None:
        if events:
            with open(self.path(job_id) / "events.jsonl", "a") as f:
                for e in events:
                    f.write(json.dumps(e) + "\n")

    def events(self, job_id: str, tail: int = 20) -> list[dict[str, Any]]:
        f = self.path(job_id) / "events.jsonl"
        if not f.exists():
            return []
        return [json.loads(l) for l in f.read_text().splitlines()[-tail:]]

    def recent(self, n: int = 10) -> list[Job]:
        ids = sorted((p.name for p in self.root.iterdir() if (p / "job.json").exists()), reverse=True)
        return [j for j in (self.load(i) for i in ids[:n]) if j]


Hook = Callable[[Job], Awaitable[None] | None]


class Runner:
    """One queue, one worker: jobs share Live, so they never overlap."""

    def __init__(self, cfg: Config, store: JobStore, on_start: Hook | None = None, on_finish: Hook | None = None,
                 run_query: Callable[..., Any] = query):
        self.cfg, self.store = cfg, store
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.on_start, self.on_finish = on_start, on_finish
        self.current: str | None = None
        self._query = run_query

    def recover(self) -> None:
        """Jobs left running by a restart are marked failed; queued ones are requeued."""
        for job in reversed(self.store.recent(50)):
            if job.status == "running":
                job.status, job.error, job.finished = "failed", "harness restarted mid-job", time.time()
                self.store.save(job)
            elif job.status == "queued":
                self.queue.put_nowait(job.id)

    def submit(self, kind: str, title: str, prompt: str, meta: dict[str, Any] | None = None) -> Job:
        job = Job(id=new_id(), kind=kind, title=title, prompt=prompt, meta=meta or {})
        self.store.save(job)
        self.queue.put_nowait(job.id)
        return job

    def pending(self, kind: str, key: str, value: Any) -> Job | None:
        """A queued (not yet started) job of this kind with meta[key] == value."""
        for job in self.store.recent(20):
            if job.kind == kind and job.status == "queued" and job.meta.get(key) == value:
                return job
        return None

    async def _hook(self, hook: Hook | None, job: Job) -> None:
        if hook:
            try:
                r = hook(job)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:  # a failed notification must not fail the job
                log.exception("hook failed")

    async def run_one(self, job: Job) -> Job:
        job.status, job.started = "running", time.time()
        self.store.save(job)
        await self._hook(self.on_start, job)
        try:
            async for msg in self._query(prompt=job.prompt, options=options(self.cfg)):
                self.store.append(job.id, _event(msg))
                sid = getattr(msg, "session_id", None)
                if sid and not job.session_id:
                    job.session_id = sid
                    self.store.save(job)
                if isinstance(msg, ResultMessage):
                    job.result = msg.result
                    job.cost_usd = msg.total_cost_usd
                    job.turns = msg.num_turns
                    job.status = "failed" if msg.is_error else "done"
                    if msg.is_error:
                        job.error = (msg.result or msg.subtype)[:2000]
            if job.status == "running":
                job.status, job.error = "failed", "session ended without a result"
        except Exception as exc:
            log.exception("job %s", job.id)
            job.status, job.error = "failed", explain(exc)
        job.finished = time.time()
        self.store.save(job)
        await self._hook(self.on_finish, job)
        return job

    async def work(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.store.load(job_id)
            if job and job.status == "queued":
                self.current = job_id
                try:
                    await self.run_one(job)
                finally:
                    self.current = None


async def ask(cfg: Config, prompt: str, run_query: Callable[..., Any] = query) -> dict[str, Any]:
    """A short read-only session; returns its answer."""
    text, result = [], None
    try:
        async for msg in run_query(prompt=prompt, options=options(cfg, ask=True)):
            if isinstance(msg, AssistantMessage):
                text += [b.text for b in msg.content if isinstance(b, TextBlock)]
            if isinstance(msg, ResultMessage):
                result = msg
    except Exception as exc:
        raise ValueError(explain(exc)) from exc
    if result is None:
        raise RuntimeError("no result")
    return {"answer": result.result or "\n".join(text), "session_id": result.session_id,
            "cost_usd": result.total_cost_usd, "error": result.is_error}
