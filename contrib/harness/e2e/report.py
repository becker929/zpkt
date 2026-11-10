"""The run's report: what passed, what failed and why, the turn by turn timeline, and where the evidence is."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .checks import Result, Run


def timeline(run: Run) -> list[tuple[float, str, str]]:
    """What happened, in order, on the page's clock: the user's actions, and what the Mac said and played."""
    msgs = run.messages()
    rows: list[tuple[float, str, str]] = [(e.t / 1000, "user", f"{e.what} {_short(e.data)}") for e in run.events]
    for e in run.page["wire"]:
        m, t = e["msg"], e["t"] / 1000
        kind = m.get("type")
        if e["dir"] == "out":
            if kind in ("say", "start", "interrupt", "end_turn", "log"):
                rows.append((t, "page", f"{kind} {m.get('text', '')[:100]}"))
            elif kind == "mic":
                rows.append((t, "page", f"mic {m.get('state')} ({m.get('open_ms', '')} ms)"))
            continue
        if kind == "speech" and m.get("state") == "begin":
            said = msgs.get(m.get("seq"), {})
            d = said.get("data", {})
            if said.get("kind") == "music":             # the app's intro to a render carries the card's seq
                heard = next((i["text"] for i in run.intros if i["seq"] == m["seq"]), "")
                rows.append((t, "speak", f"[intro] for #{m['seq']} {d.get('title', '')!r}: heard {heard[:110]!r}"))
            else:
                rows.append((t, "speak", f"[{d.get('role', '?')}] {d.get('text', '')[:140]}"))
        elif kind == "play":
            d = msgs.get(m["seq"], {}).get("data", {})
            rows.append((t, "play", f"#{m['seq']} {d.get('title', '')!r} x{m.get('loops', 1)}"))
        elif kind in ("listen", "unlisten", "stop_audio"):
            rows.append((t, "mac", kind))
        elif kind == "upsert":
            mm = m["message"]
            if mm["kind"] == "music" and mm.get("rev", 0) == 0:
                rows.append((t, "card", f"#{mm['seq']} {mm['data'].get('title', '')!r}"
                             f"{' (options)' if mm['data'].get('options') else ' (A/B)' if mm['data'].get('ab') else ''}"))
            elif mm["kind"] == "user" and mm["data"].get("text"):
                rows.append((t, "heard", mm["data"]["text"][:140]))
            elif mm["kind"] == "notice":
                rows.append((t, "notice", mm["data"].get("text", "")[:140]))
    rows.sort(key=lambda r: r[0])
    seen, out = set(), []
    for r in rows:
        if (round(r[0], 2), r[1], r[2]) not in seen:
            seen.add((round(r[0], 2), r[1], r[2]))
            out.append(r)
    return out


def _short(d: dict[str, Any]) -> str:
    return json.dumps(d)[:140] if d else ""


def write(folder: Path, results: list[Result], run: Run | None, meta: dict[str, Any]) -> Path:
    passed = sum(r.ok for r in results)
    lines = [f"# studio end-to-end run, {meta['started']}", "",
             f"**{passed} of {len(results)} checks passed.** Suite: {meta.get('suite', '?')}, "
             f"{meta.get('claude', '?')} Claude. Parts: {', '.join(meta['parts'])}. "
             f"Browser: {meta['browser']}. Commit {meta['commit']}. Renders: {meta['renders']}.", "",
             "| | check | result |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {'PASS' if r.ok else '**FAIL**'} | {r.name} | {r.detail.replace('|', '/')} |")
    lines += ["", "## Evidence for failures", ""]
    for r in results:
        if not r.ok:
            lines.append(f"### {r.name}\n\n{r.detail}\n")
            lines += [f"- {e}" for e in r.evidence[:12]] + [""]
    if run is not None:
        lines += ["## Timeline (page clock, s)", "", "| t | who | what |", "|---|---|---|"]
        rows = timeline(run)
        t0 = rows[0][0] if rows else 0
        for t, who, what in rows:
            lines.append(f"| {t - t0:7.1f} | {who} | {what.replace('|', '/')} |")
    lines += ["", "## Files", "", "- `report.json`: every check, with its evidence",
              "- `screens/`: screenshots at each step and at any timeout", "- `heard-*.wav`: what the speakers played",
              "- `wire.json`: the socket both ways; `engine.json`: every item the page played",
              "- `studio/studio.sqlite3`: the chat and the turn timings (`harness timings` reads the same table)"]
    path = folder / "report.md"
    path.write_text("\n".join(lines) + "\n")
    (folder / "report.json").write_text(json.dumps({"meta": meta, "results": [asdict(r) for r in results]}, indent=1))
    return path


def commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent).stdout.strip() + (
            "+changes" if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                                         cwd=Path(__file__).parent).stdout.strip() else "")
    except OSError:
        return "?"
