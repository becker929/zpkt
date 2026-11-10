#!/usr/bin/env python3
"""Stream TMS agent activity from the Letta API in real-time.

Usage:
    uv run scripts/stream_agent.py [--base-url URL] [--agent-id ID] [--history N]

Shows: user messages, assistant messages, tool calls (with args),
tool returns (truncated), and timing. Polls every 2s.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ANSI colours
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_BLUE = "\033[34m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_RED = "\033[31m"


def _get(url: str, timeout: int = 10) -> object:
    req = urllib.request.Request(url)
    if os.environ.get("LETTA_API_KEY"):  # Letta runs with a server password
        req.add_header("Authorization", f"Bearer {os.environ['LETTA_API_KEY']}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _find_agent(base_url: str, agent_id: str | None) -> tuple[str, str]:
    if agent_id:
        agent = _get(f"{base_url}/v1/agents/{agent_id}")
        return agent["id"], agent.get("name", agent_id)
    agents = _get(f"{base_url}/v1/agents/")
    for a in agents:
        if a.get("name", "").lower() in ("tms", "vibe"):
            return a["id"], a["name"]
    if agents:
        return agents[0]["id"], agents[0].get("name", "?")
    print(f"{_RED}No agents found on {base_url}{_RESET}")
    sys.exit(1)


def _ts(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ""


def _truncate(s: str, maxlen: int = 300) -> str:
    s = s.replace("\n", " ↵ ")
    return s[:maxlen] + "…" if len(s) > maxlen else s


def _format_message(msg: dict) -> str | None:
    """Format a single Letta message for terminal display. Returns None to skip."""
    mt = msg.get("messageType") or msg.get("message_type") or ""
    ts = _ts(msg.get("date") or msg.get("created_at"))
    prefix = f"{_DIM}{ts}{_RESET} " if ts else ""

    if mt == "user_message":
        content = msg.get("content", "")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    if parsed.get("type") == "heartbeat":
                        return None
                    content = parsed.get("message", content)
            except (json.JSONDecodeError, TypeError):
                pass
        return f"{prefix}{_BLUE}{_BOLD}[user]{_RESET} {_truncate(str(content))}"

    if mt == "assistant_message":
        content = msg.get("content", "")
        return f"{prefix}{_GREEN}{_BOLD}[assistant]{_RESET} {_truncate(str(content), 500)}"

    if mt == "tool_call_message":
        tc = msg.get("toolCall") or msg.get("tool_call") or {}
        name = tc.get("name", "?")
        args = tc.get("arguments", "")
        if isinstance(args, str) and len(args) > 200:
            try:
                parsed_args = json.loads(args)
                args = json.dumps(parsed_args, indent=None)[:200] + "…"
            except (json.JSONDecodeError, TypeError):
                args = args[:200] + "…"
        color = _YELLOW
        if name in ("request_improvement", "run_shell_command"):
            color = _RED
        return f"{prefix}{color}{_BOLD}[tool_call]{_RESET} {_BOLD}{name}{_RESET}({args})"

    if mt == "tool_return_message":
        ret = msg.get("toolReturn") or msg.get("tool_return") or ""
        status = msg.get("status") or ""
        status_tag = f" [{status}]" if status and status != "success" else ""
        return f"{prefix}{_MAGENTA}[tool_return{status_tag}]{_RESET} {_truncate(str(ret))}"

    if mt == "reasoning_message":
        content = msg.get("reasoning") or msg.get("content") or ""
        return f"{prefix}{_DIM}[thinking]{_RESET} {_DIM}{_truncate(str(content), 200)}{_RESET}"

    if mt == "system_message":
        return None

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LETTA_BASE_URL", "http://localhost:8283"),
    )
    parser.add_argument("--agent-id", default=None)
    parser.add_argument(
        "--history", type=int, default=20,
        help="How many recent messages to show at startup (0 = skip all)",
    )
    args = parser.parse_args()

    agent_id, agent_name = _find_agent(args.base_url, args.agent_id)
    print(f"{_CYAN}{_BOLD}Streaming agent: {agent_name}{_RESET} ({agent_id})")
    print(f"{_DIM}Polling {args.base_url} every 2s — Ctrl-C to stop{_RESET}\n")

    seen_ids: set[str] = set()

    try:
        all_msgs = _get(f"{args.base_url}/v1/agents/{agent_id}/messages?limit=1000")
    except Exception as exc:
        print(f"{_RED}Cannot fetch messages: {exc}{_RESET}")
        sys.exit(1)

    if not isinstance(all_msgs, list):
        all_msgs = []

    if args.history > 0 and all_msgs:
        show = all_msgs[-args.history :]
        skip = all_msgs[: -args.history] if len(all_msgs) > args.history else []
        for m in skip:
            seen_ids.add(m.get("id", ""))

        if skip:
            print(f"{_DIM}(skipped {len(skip)} older messages){_RESET}\n")

        for m in show:
            mid = m.get("id", "")
            seen_ids.add(mid)
            line = _format_message(m)
            if line:
                print(line)
        if show:
            print(f"\n{_DIM}--- live tail ---{_RESET}\n")
    else:
        for m in all_msgs:
            seen_ids.add(m.get("id", ""))
        print(f"{_DIM}(skipped {len(seen_ids)} existing messages){_RESET}\n")

    try:
        while True:
            time.sleep(2)
            try:
                msgs = _get(f"{args.base_url}/v1/agents/{agent_id}/messages?limit=50")
            except Exception:
                continue

            if not isinstance(msgs, list):
                continue

            new_msgs = [m for m in msgs if m.get("id", "") not in seen_ids]
            for m in new_msgs:
                seen_ids.add(m.get("id", ""))
                line = _format_message(m)
                if line:
                    print(line)

    except KeyboardInterrupt:
        print(f"\n{_DIM}stopped{_RESET}")


if __name__ == "__main__":
    main()
