# Self-modify module
"""Self-modification module for the agent harness.

Uses the Claude Agent SDK to apply targeted code edits, then restarts the
services whose source files were touched.

Public API
----------
    apply_improvement(description, prompt, restart?, progress_callback?)  -- full workflow (async)
    restart_service(name)                             -- stop + start one service
    services_for_paths(paths)                         -- infer services from file list

Letta path
----------
    Vibe calls POST /self-improve on the vibe server (port 8080), which starts
    apply_improvement() in a background thread and returns a job_id immediately.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SDK_LOG = Path("/tmp/vibe-sdk-session.log")
IMPROVEMENT_PERSIST = Path("/tmp/vibe-improvement-last.json")

# ── Workspace roots ────────────────────────────────────────────────────────────

WORKSPACE = Path(__file__).parents[3]   # .../agent-sandbox
HANDS_DIR = WORKSPACE / "hands"

# ── File prefix → services that must restart when those files change ───────────
#
# Keys are path prefixes relative to WORKSPACE.
# Values are lists of make target suffixes (make stop-X / make start-X).
# A path matching multiple prefixes unions all service lists.
#
# Special sentinel "__setup_tools__" means run `make setup-tools` instead.

_RESTART_MAP: dict[str, list[str]] = {
    "hands/src/hands/vibe/": ["vibe"],
    "hands/src/hands/mcp_server.py": ["ableton-mcp"],
    "hands/src/hands/": ["vibe", "ableton-mcp"],
    "hands/frontend/": ["frontend"],
    "hands/scripts/setup_letta_tools.py": ["__setup_tools__"],
    ".cursor/skills/": [],
    ".cursorrules": [],
    "hands/Makefile": [],
}


def services_for_paths(changed_paths: list[str]) -> tuple[list[str], bool]:
    """Infer which services to restart from a list of changed file paths.

    Returns (service_names, needs_setup_tools).
    Paths should be relative to WORKSPACE (as returned by git diff --name-only).
    Letta is never included — it requires explicit manual restart.

    Uses longest-prefix-first matching so that a specific rule (e.g.
    hands/src/hands/vibe/) wins over a broader one (hands/src/hands/).
    """
    sorted_map = sorted(_RESTART_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
    needed: set[str] = set()
    setup_tools = False
    for path in changed_paths:
        for prefix, services in sorted_map:
            if path.startswith(prefix):
                for s in services:
                    if s == "__setup_tools__":
                        setup_tools = True
                    else:
                        needed.add(s)
                break  # longest match wins; skip remaining prefixes for this path
    return sorted(needed), setup_tools


# ── Makefile helpers ───────────────────────────────────────────────────────────

def _make(target: str, timeout: int = 60) -> str:
    """Run a make target in hands/Makefile. Returns combined stdout+stderr."""
    result = subprocess.run(
        ["make", "-C", str(HANDS_DIR), target],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (result.stdout + result.stderr).strip()


def restart_service(name: str) -> str:
    """Stop then start a single named service. Returns log output."""
    stop_out = _make(f"stop-{name}")
    start_out = _make(f"start-{name}")
    return f"[stop-{name}] {stop_out}\n[start-{name}] {start_out}"


def run_setup_tools() -> str:
    """Re-register all Letta tools (idempotent). Returns log output."""
    return _make("setup-tools", timeout=120)


# ── Git helpers ────────────────────────────────────────────────────────────────

def _git_changed_files() -> list[str]:
    """Return files changed since last commit (staged + unstaged)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(WORKSPACE),
    )
    lines = result.stdout.strip().splitlines()
    # Also include untracked new files
    result2 = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=str(WORKSPACE),
    )
    lines += result2.stdout.strip().splitlines()
    return [ln.strip() for ln in lines if ln.strip()]


# ── SDK session logger ─────────────────────────────────────────────────────────

def _sdk_log(line: str, callback: Callable[[str], None] | None = None) -> None:
    """Append a timestamped line to the SDK session log and vibe stdout.

    If callback is provided it is called with the raw line (no timestamp) so
    callers (e.g. the vibe server's background job) can stream progress in
    real-time.
    """
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {line}\n"
    print(f"  [sdk] {line}")
    try:
        with SDK_LOG.open("a") as fh:
            fh.write(entry)
    except OSError:
        pass
    if callback is not None:
        try:
            callback(line)
        except Exception:
            pass


def _log_message(
    message: Any,
    callback: Callable[[str], None] | None = None,
) -> None:
    """Extract and log the interesting parts of an SDK stream message."""
    cls = type(message).__name__

    if cls == "AssistantMessage":
        raw = getattr(message, "message", {})
        content = raw.get("content", []) if isinstance(raw, dict) else []
        for block in content:
            if not isinstance(block, dict):
                block = getattr(block, "__dict__", {})
            btype = block.get("type", "")
            if btype == "thinking":
                snippet = (block.get("thinking") or "")[:200].replace("\n", " ")
                _sdk_log(f"[think] {snippet}", callback)
            elif btype == "text":
                snippet = (block.get("text") or "")[:300].replace("\n", " ")
                if snippet.strip():
                    _sdk_log(f"[text] {snippet}", callback)
            elif btype == "tool_use":
                inp = json.dumps(block.get("input", {}))[:250]
                _sdk_log(f"[tool→] {block.get('name', '?')} {inp}", callback)
            elif btype == "tool_result":
                content_inner = block.get("content", "")
                if isinstance(content_inner, list):
                    content_inner = " ".join(
                        c.get("text", "") for c in content_inner if isinstance(c, dict)
                    )
                snippet = str(content_inner)[:250].replace("\n", " ")
                _sdk_log(f"[tool←] {snippet}", callback)

    elif cls == "ResultMessage":
        result = (getattr(message, "result", "") or "")[:300].replace("\n", " ")
        _sdk_log(f"[done] turns={getattr(message, 'num_turns', '?')} {result}", callback)

    elif cls == "RateLimitEvent":
        info = getattr(message, "rate_limit_info", None)
        if info:
            _sdk_log(
                f"[rate-limit] status={getattr(info, 'status', '?')} "
                f"utilization={getattr(info, 'utilization', '?')}",
                callback,
            )


# ── Claude Agent SDK wrapper ───────────────────────────────────────────────────

async def run_agent_edit(
    prompt: str,
    max_turns: int = 40,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """Spawn a Claude Agent SDK session to make code edits.

    The session runs with bypassPermissions so it can edit files and run
    shell commands headlessly. Streams all messages to /tmp/vibe-sdk-session.log
    and vibe server stdout for real-time observability.

    If progress_callback is provided, it is called with each log line as the
    session runs, enabling callers to stream progress to external consumers.

    Raises ImportError if claude-agent-sdk is not installed.
    Install with: uv pip install "hands[self-improve]"
    """
    from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore[import]

    SDK_LOG.write_text(
        f"SDK session started: {datetime.now(timezone.utc).isoformat()}\n"
        f"prompt: {prompt[:200]}\n"
        f"{'─' * 60}\n"
    )

    options = ClaudeAgentOptions(
        cwd=str(WORKSPACE),
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": (
                "You are making targeted improvements to the agent harness at "
                f"{WORKSPACE}. "
                "When given a bug report or feature request, investigate the root "
                "cause in the codebase before making changes. Read the relevant "
                "source files, check git history (git log -p), and look for "
                "predecessor implementations (e.g. in ableton-live-vm/) that may "
                "have handled the same problem correctly. Fix the root cause, not "
                "just the described symptom. "
                "Do not install new packages or change pyproject.toml unless "
                "explicitly instructed. "
                "After editing, run ReadLints on every changed file and fix any "
                "introduced linter errors before finishing."
            ),
        },
        setting_sources=["project"],
        stderr=lambda line: _sdk_log(f"[stderr] {line}", progress_callback),
    )

    final_result = ""
    async for message in query(prompt=prompt, options=options):
        _log_message(message, progress_callback)
        from claude_agent_sdk import ResultMessage  # type: ignore[import]
        if isinstance(message, ResultMessage):
            final_result = message.result or ""

    return final_result


# ── Full workflow ──────────────────────────────────────────────────────────────

async def apply_improvement(
    description: str,
    prompt: str,
    restart: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Apply a self-improvement to the agent harness end-to-end.

    Steps:
      1. Snapshot changed files before the edit (git diff HEAD).
      2. Run the Claude Agent SDK session.
      3. Diff changed files after the edit.
      4. Infer which services to restart (or use caller-supplied list).
      5. Restart services and optionally run setup-tools.

    Args:
        description:       Short human-readable label for the improvement.
        prompt:            Full instructions for the Claude Agent SDK session.
        restart:           Optional override list of service names to restart.
                           Pass [] to skip all restarts.
        progress_callback: Optional callable(line: str) invoked for each SDK
                           log line. Enables callers to stream progress in
                           real-time (e.g. vibe server background job).

    Returns a dict with keys:
        description, agent_result, changed_files,
        restarted_services, setup_tools_run, restart_log.
    """
    files_before = set(_git_changed_files())

    agent_result = await run_agent_edit(prompt, progress_callback=progress_callback)

    files_after = set(_git_changed_files())
    new_changed = sorted(files_after - files_before) or sorted(files_after)

    if restart is None:
        inferred, needs_setup = services_for_paths(new_changed)
    else:
        inferred = restart
        needs_setup = False

    # Persist result before restarting — the vibe process may be killed mid-restart,
    # which would wipe the in-memory job state. The new process reads this file on
    # startup so the frontend receives the correct "completed" status after reconnect.
    _persist_result = {
        "status": "completed",
        "description": description,
        "agent_result": agent_result,
        "changed_files": new_changed,
        "restarted_services": inferred,
        "setup_tools_run": needs_setup,
    }
    try:
        IMPROVEMENT_PERSIST.write_text(json.dumps(_persist_result))
    except OSError:
        pass

    restart_log: dict[str, str] = {}
    for svc in inferred:
        try:
            restart_log[svc] = restart_service(svc)
        except subprocess.TimeoutExpired:
            restart_log[svc] = f"TIMEOUT: {svc} restart timed out (60s)"
        except Exception as exc:
            restart_log[svc] = f"ERROR: {exc}"

    setup_log = ""
    if needs_setup:
        try:
            setup_log = run_setup_tools()
        except Exception as exc:
            setup_log = f"ERROR: {exc}"

    return {
        "description": description,
        "agent_result": agent_result,
        "changed_files": new_changed,
        "restarted_services": inferred,
        "setup_tools_run": needs_setup,
        "restart_log": restart_log,
        "setup_log": setup_log,
    }
