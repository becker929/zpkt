"""Compaction: one long conversation kept inside an engine's budget. Pure: events in, a plan or text out.

The transcript on disk is never cut. When the part of it an engine would be handed is past the engine's budget, the
service (service.py) has the engine write a summary of the older turns, starts the engine again on the summary and the
last few turns word for word, and appends a `compacted` event that says where the kept turns begin (`keep_from`, a
seq). Everything after reads the conversation from the last `compacted` event on. Tokens are estimated from
characters. The pages an agent made are read from its make_page results, so their links survive whatever the summary
says.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from zpkt.app.ask.events import ENGINES, Event, dialogue

KEEP_TURNS = 3  # the last turns an engine gets word for word after a compaction
CHARS_PER_TOKEN = 4
BUDGET_TOKENS = {"claude": 100_000, "gemini": 200_000}  # compact when the conversation is estimated past this
BUDGET_ENV = "ZPKT_ASK_COMPACT_TOKENS"  # "120000" for every engine, or "claude=120000,gemini=300000"; 0 is never
RECENT_CHARS = 24_000
SUMMARY_INPUT_CHARS = 160_000
MAX_SUMMARY_CHARS = 12_000
PAGE_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((/app/#page=([\w.\-]+))\)")

INSTRUCTIONS = """You are compacting one long conversation between a music producer and the assistant in the zpkt app, so that it can go on in a fresh context. Write the summary the assistant will read instead of the older turns.

Use these headings, in this order, in plain markdown:
## What the user wants
## Decisions
## Pages made
## Open questions
## Project in play

Rules: keep names, numbers, file paths, page ids and links exactly as they were written. Under "Pages made" give each page as a markdown link with its id. Write "None." under a heading that has nothing. At most 600 words. Do not use any tool. Reply with the summary and nothing else."""


def budgets(environ: Mapping[str, str], given: Mapping[str, int] | None = None) -> dict[str, int]:
    """The budget of each engine in tokens: the defaults, then the environment's setting, then `given`."""
    out = dict(BUDGET_TOKENS)
    for part in (environ.get(BUDGET_ENV) or "").split(","):
        name, _, number = part.strip().rpartition("=")
        if not number.strip().isdigit():
            continue
        for engine in [name.strip()] if name.strip() else ENGINES:
            if engine in ENGINES:
                out[engine] = int(number)
    return {**out, **(given or {})}


def base(events: Sequence[Event]) -> Event | None:
    """The last `compacted` event: where the conversation an engine is handed now begins."""
    return next((e for e in reversed(events) if e.get("type") == "compacted"), None)


def seq(e: Event) -> int:
    n = e.get("seq")
    return n if isinstance(n, int) else -1


def window(events: Sequence[Event], upto: int | None = None) -> list[Event]:
    """The events an engine that starts now must know of: all of them, or those from the last compaction's
    `keep_from` on. `upto` leaves out a seq and all after it (the prompt being sent)."""
    b = base(events)
    start = int(b["keep_from"]) if b is not None and isinstance(b.get("keep_from"), int) else 0
    return [
        e
        for e in events
        if e.get("type") not in ("compacted", "compacting") and seq(e) >= start and (upto is None or seq(e) < upto)
    ]


def weigh(e: Event) -> int:
    """About how many characters of an engine's context an event takes."""
    if e.get("parent"):
        return 0  # a subagent's own work stays in the subagent
    kind = e.get("type")
    if kind == "prompt":
        return len(str(e.get("text") or ""))
    if kind == "message":
        return len(str(e.get("content") or ""))
    if kind == "tool_use":
        return len(json.dumps(e.get("parameters") or {})) + len(str(e.get("tool_name") or ""))
    if kind == "tool_result":
        out = e.get("output")
        return len(out if isinstance(out, str) else json.dumps(out if out is not None else ""))
    return 0


def estimate(events: Sequence[Event]) -> int:
    """Tokens of the conversation as an engine holds it now. After a compaction that is the summary, the kept turns
    as text, and everything since in full."""
    b = base(events)
    if b is None:
        return sum(weigh(e) for e in events) // CHARS_PER_TOKEN
    kept = [e for e in window(events) if seq(e) < seq(b)]
    since = [e for e in events if seq(e) > seq(b)]
    chars = len(str(b.get("summary") or "")) + len(dialogue(kept, RECENT_CHARS)) + sum(weigh(e) for e in since)
    return chars // CHARS_PER_TOKEN


def pages_made(events: Sequence[Event]) -> list[dict[str, str]]:
    """The pages the agents made, from their make_page results: [{id, title, link}], each id once."""
    out: dict[str, dict[str, str]] = {}
    for e in events:
        if e.get("type") != "tool_result" or e.get("status") == "error":
            continue
        text = e.get("output")
        for title, link, page_id in PAGE_LINK.findall(text if isinstance(text, str) else json.dumps(text)):
            out[page_id] = {"id": page_id, "title": title, "link": link}
    return list(out.values())


@dataclass
class Plan:
    """What a compaction will do: summarise `old`, keep everything from the seq `keep_from` word for word."""

    old: list[Event]
    keep_from: int
    turns: int  # how many turns `old` holds
    tokens: int  # the estimate that was past the budget
    earlier: str = ""  # the summary of the compaction before this one
    pages: list[dict[str, str]] = field(default_factory=list)  # every page made so far
    project: str = ""


def plan(events: Sequence[Event], budget: int, keep: int = KEEP_TURNS, project: str = "") -> Plan | None:
    """A Plan when the conversation is past `budget` tokens and has a turn to summarise; else None."""
    tokens = estimate(events)
    if budget <= 0 or tokens <= budget:
        return None
    mine = window(events)
    starts = [seq(e) for e in mine if e.get("type") == "prompt" and not e.get("auto")]
    if not starts:
        return None
    kept = min(max(keep, 0), len(starts) - 1)  # at least one turn is summarised
    keep_from = starts[-kept] if kept else seq(events[-1]) + 1
    old = [e for e in mine if seq(e) < keep_from]
    b = base(events)
    before = list((b or {}).get("pages") or [])
    pages = {p["id"]: p for p in [*before, *pages_made(old)] if isinstance(p, dict) and p.get("id")}
    return Plan(
        old=old,
        keep_from=keep_from,
        turns=len(starts) - kept,
        tokens=tokens,
        earlier=str((b or {}).get("summary") or ""),
        pages=list(pages.values()),
        project=project,
    )


def page_lines(pages: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(f"- [{p['title']}]({p['link']}) (id `{p['id']}`)" for p in pages)


def summary_prompt(p: Plan) -> str:
    """What the engine is asked, to write the summary."""
    parts = [INSTRUCTIONS]
    if p.earlier:
        parts.append(f"<earlier-summary>\n{p.earlier}\n</earlier-summary>")
    if p.pages:
        parts.append(f"<pages-made>\n{page_lines(p.pages)}\n</pages-made>")
    if p.project:
        parts.append(f"<project>{p.project}</project>")
    parts.append(f"<conversation>\n{dialogue(p.old, SUMMARY_INPUT_CHARS, detail=True)}\n</conversation>")
    return "\n\n".join(parts)


def clean(summary: str) -> str:
    text = summary.strip()
    return text if len(text) <= MAX_SUMMARY_CHARS else text[:MAX_SUMMARY_CHARS].rstrip() + "\n…(summary cut)…"


def compacted(p: Plan, engine: str, summary: str, error: str = "") -> Event:
    """The transcript's marker. With `error` the summary could not be written: `summary` is then the earlier one."""
    ev: Event = {
        "type": "compacted",
        "engine": engine,
        "summary": summary,
        "keep_from": p.keep_from,
        "turns": p.turns,
        "tokens": p.tokens,
        "pages": p.pages,
    }
    if error:
        ev |= {"failed": True, "error": error[:400]}
    return ev


def preamble(events: Sequence[Event], upto: int | None = None) -> str:
    """What an engine that starts after a compaction reads before the person's words: the summary, the pages and
    the turns since `keep_from`. Empty when the conversation was never compacted."""
    b = base(events)
    if b is None:
        return ""
    parts = ["This is one long conversation. Its older turns were compacted so that it can go on."]
    summary = str(b.get("summary") or "").strip()
    if summary:
        parts.append(f"Summary of the older turns:\n\n{summary}")
    else:
        parts.append("The summary of the older turns could not be written; only the last turns are below.")
    pages = [p for p in b.get("pages") or [] if isinstance(p, dict) and p.get("id")]
    if pages:
        parts.append(f"Pages made so far:\n{page_lines(pages)}")
    recent = dialogue(window(events, upto), RECENT_CHARS)
    if recent:
        parts.append(f"The last turns, word for word:\n\n{recent}")
    return "\n\n".join(parts) + "\n\n---\n\n"
