"""Vibe stack watchdog — standalone self-healing probe.

Runs independently of the vibe stack. Probes all four services on a fixed
interval and escalates through three recovery tiers when liveness is lost:

  Tier 1 (fail 1-2)  : restart the failed service only
  Tier 2 (fail 3)    : restart the full stack
  Tier 3 (fail 4)    : Claude Agent SDK diagnostic + fix session
  Backoff (fail 5+)  : exponential back-off, write report to /tmp

Stop signals
------------
  - ``touch hands/.watchdog-stop`` (sentinel file, checked each loop)
  - SIGTERM / SIGINT

Usage
-----
  uv run scripts/watchdog.py                       # foreground
  uv run scripts/watchdog.py --pid-file .pids/watchdog.pid  # Makefile path
  make watchdog                                     # backgrounded via Makefile
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths & constants ──────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
HANDS_DIR = SCRIPT_DIR.parent          # hands/
WORKSPACE = HANDS_DIR.parent           # agent-sandbox/

SENTINEL = HANDS_DIR / ".watchdog-stop"
WATCHDOG_LOG = Path("/tmp/vibe-watchdog.log")
REPORT_PATH = Path("/tmp/vibe-watchdog-report.txt")

PROBE_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "20"))   # seconds
PROBE_TIMEOUT = 5                                                   # seconds per HTTP probe
SDK_COOLDOWN = 600                                                  # 10 min between SDK sessions
MAX_BACKOFF = 300                                                    # 5 min max sleep

LETTA_CONTAINER = "letta-vibe"
LETTA_LOG_CMD = ["docker", "logs", "--tail=50", LETTA_CONTAINER]

SERVICE_LOGS: dict[str, str | None] = {
    "letta":      None,                        # Docker — use docker logs
    "vibe":       "/tmp/vibe-server.log",
    "ableton-mcp": "/tmp/ableton-mcp-bridge.log",
    "frontend":   "/tmp/vibe-frontend.log",
}

# ── Logging ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg: str) -> None:
    line = f"[{_ts()}] {msg}"
    # When stdout is redirected to the log file (Makefile path), we only need
    # print(). The explicit file write is for foreground runs where stdout is a
    # terminal and we also want a persistent log.
    print(line, flush=True)
    stdout_is_tty = sys.stdout.isatty()
    if stdout_is_tty:
        try:
            with WATCHDOG_LOG.open("a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


# ── Service probe definition ──────────────────────────────────────────────────

@dataclass
class ServiceProbe:
    name: str
    url: str
    method: str = "GET"
    restart_target: str = ""    # make target suffix, e.g. "vibe" → make stop-vibe start-vibe
    fail_count: int = 0
    # extra validation callable(response_body: bytes) -> bool
    validate: Any = None        # type: ignore[type-arg]
    # SDK escalation cooldown state (shared across all probes via module-level var)

    def label(self) -> str:
        return self.name.upper()


def _validate_json(body: bytes) -> bool:
    try:
        json.loads(body)
        return True
    except Exception:
        return False


PROBES: list[ServiceProbe] = [
    ServiceProbe(
        name="letta",
        url="http://localhost:8283/v1/health",
        restart_target="letta",
    ),
    ServiceProbe(
        name="vibe",
        url="http://localhost:8080/session",
        restart_target="vibe",
        validate=_validate_json,
    ),
    ServiceProbe(
        name="ableton-mcp",
        url="http://localhost:9010/mcp",
        method="POST",
        restart_target="ableton-mcp",
    ),
    ServiceProbe(
        name="frontend",
        url="http://localhost:3000",
        restart_target="frontend",
    ),
]


# ── HTTP probe ────────────────────────────────────────────────────────────────

def probe_service(probe: ServiceProbe) -> bool:
    """Return True if the service is healthy."""
    try:
        req = urllib.request.Request(probe.url, method=probe.method)
        if probe.method == "POST":
            # Minimal MCP initialize payload so the bridge responds
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "watchdog", "version": "1.0"},
                },
            }).encode()
            req = urllib.request.Request(
                probe.url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            body = resp.read()
            if probe.validate is not None:
                return probe.validate(body)
            return True
    except urllib.error.HTTPError as exc:
        # Any HTTP response (even 4xx) means the process is alive.
        # For the MCP bridge an initialize may yield a non-200 but the server is up.
        if probe.name == "ableton-mcp" and exc.code < 500:
            return True
        return False
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


# ── Log helpers ───────────────────────────────────────────────────────────────

def tail_log(service_name: str, n: int = 40) -> str:
    log_path = SERVICE_LOGS.get(service_name)
    if log_path is None:
        # Docker logs for Letta
        try:
            result = subprocess.run(
                LETTA_LOG_CMD,
                capture_output=True, text=True, timeout=10,
            )
            return (result.stdout + result.stderr).strip()[-3000:]
        except Exception as exc:
            return f"(docker logs failed: {exc})"
    p = Path(log_path)
    if not p.exists():
        return "(no log file)"
    try:
        lines = p.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(log unreadable)"


# ── Make helpers ──────────────────────────────────────────────────────────────

def _make(*targets: str, timeout: int = 120) -> tuple[bool, str]:
    """Run make targets in hands/. Returns (success, combined output)."""
    cmd = ["make", "-C", str(HANDS_DIR)] + list(targets)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        out = (result.stdout + result.stderr).strip()
        return result.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "(make timed out)"
    except Exception as exc:
        return False, str(exc)


def restart_service(probe: ServiceProbe) -> bool:
    """Tier 1: restart only the failed service. Returns True if now healthy."""
    if probe.name == "letta":
        log(f"  [tier1] starting letta container (preserving state)")
        try:
            subprocess.run(
                ["docker", "start", LETTA_CONTAINER],
                capture_output=True, timeout=30,
            )
        except Exception as exc:
            log(f"  [tier1] docker start failed: {exc}")
            return False
    else:
        log(f"  [tier1] make stop-{probe.restart_target} start-{probe.restart_target}")
        ok, out = _make(f"stop-{probe.restart_target}", f"start-{probe.restart_target}")
        if not ok:
            log(f"  [tier1] make error: {out[:200]}")

    time.sleep(5)
    return probe_service(probe)


def restart_all() -> bool:
    """Tier 2: stop and restart the full stack. Returns True if all healthy."""
    log("  [tier2] full stack restart: make stop start")
    _make("stop", timeout=60)
    time.sleep(3)
    ok, out = _make("start", timeout=180)
    if not ok:
        log(f"  [tier2] start returned non-zero: {out[:200]}")
    time.sleep(10)
    return all(probe_service(p) for p in PROBES)


# ── SDK escalation ────────────────────────────────────────────────────────────

_last_sdk_time: float = 0.0


def escalate_to_sdk(probe: ServiceProbe) -> None:
    """Tier 3: spawn a Claude Agent SDK session to diagnose and fix."""
    global _last_sdk_time
    now = time.monotonic()
    if now - _last_sdk_time < SDK_COOLDOWN:
        remaining = int(SDK_COOLDOWN - (now - _last_sdk_time))
        log(f"  [tier3] SDK cooldown active — {remaining}s remaining, skipping")
        return

    _last_sdk_time = now

    logs = tail_log(probe.name, 60)
    all_status = []
    for p in PROBES:
        healthy = probe_service(p)
        all_status.append(f"  {p.name}: {'OK' if healthy else 'DOWN'}")

    prompt = (
        f"The vibe stack watchdog has detected that the '{probe.name}' service "
        f"is unresponsive at {probe.url}. A Tier 1 individual restart and a "
        f"Tier 2 full-stack restart both failed to restore liveness.\n\n"
        f"Current service status:\n" + "\n".join(all_status) + "\n\n"
        f"Recent logs for '{probe.name}':\n```\n{logs}\n```\n\n"
        f"Please investigate the root cause. Check the source files for the "
        f"'{probe.name}' service, look at recent git changes (git log -p --since='2 hours ago'), "
        f"and inspect any error messages in the logs. Fix the root cause — do NOT just "
        f"restart the service. After any code change, run 'make -C hands start' to verify "
        f"the fix, then check that all services are reachable."
    )

    log(f"  [tier3] spawning Claude Agent SDK diagnostic session for '{probe.name}'")
    try:
        sys.path.insert(0, str(HANDS_DIR / "src"))
        from hands.self_modify import run_agent_edit  # type: ignore[import]
        import asyncio

        def _progress(line: str) -> None:
            log(f"  [sdk] {line}")

        asyncio.run(run_agent_edit(prompt, max_turns=30, progress_callback=_progress))
        log(f"  [tier3] SDK session complete")
    except ImportError:
        log("  [tier3] hands.self_modify unavailable — skipping SDK escalation")
    except Exception as exc:
        log(f"  [tier3] SDK session error: {exc}")


# ── Diagnostic report ─────────────────────────────────────────────────────────

def write_report(probe: ServiceProbe) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Vibe Watchdog Report — {ts}",
        f"Triggered by: {probe.name} (fail_count={probe.fail_count})",
        "",
    ]
    for p in PROBES:
        healthy = probe_service(p)
        lines.append(f"  {p.name:15s} {'OK' if healthy else 'DOWN'}")
    lines.append("")
    for p in PROBES:
        lines.append(f"=== {p.name} logs ===")
        lines.append(tail_log(p.name, 30))
        lines.append("")
    try:
        REPORT_PATH.write_text("\n".join(lines))
        log(f"  [report] written to {REPORT_PATH}")
    except OSError:
        pass


# ── Interruptible sleep ───────────────────────────────────────────────────────

def _interruptible_sleep(seconds: float, tick: float = 1.0) -> None:
    """Sleep for `seconds` but wake early if _stopped or the sentinel appears."""
    global _stopped
    deadline = time.monotonic() + seconds
    while not _stopped and time.monotonic() < deadline:
        if SENTINEL.exists():
            _stopped = True
            return
        time.sleep(min(tick, max(0.0, deadline - time.monotonic())))


# ── Main loop ─────────────────────────────────────────────────────────────────

_stopped = False


def _handle_signal(signum: int, frame: Any) -> None:
    global _stopped
    log(f"[watchdog] received signal {signum} — stopping")
    _stopped = True


def main() -> None:
    global _stopped

    parser = argparse.ArgumentParser(description="Vibe stack watchdog")
    parser.add_argument(
        "--pid-file", default="",
        help="Path to write this process's PID (so make stop-watchdog kills the right process)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    pid = os.getpid()
    if args.pid_file:
        try:
            Path(args.pid_file).write_text(str(pid))
        except OSError as exc:
            log(f"[watchdog] warning: could not write pid file {args.pid_file}: {exc}")

    log(f"[watchdog] started  pid={pid}  interval={PROBE_INTERVAL}s")
    log(f"[watchdog] stop sentinel: {SENTINEL}")
    log(f"[watchdog] probing: {', '.join(p.name for p in PROBES)}")

    extra_sleep = 0  # backoff accumulator
    cycle = 0
    HEARTBEAT_EVERY = int(os.environ.get("WATCHDOG_HEARTBEAT_EVERY", "1"))

    while not _stopped:
        if SENTINEL.exists():
            log("[watchdog] sentinel file detected — stopping cleanly")
            SENTINEL.unlink(missing_ok=True)
            break

        cycle += 1
        all_healthy_this_cycle = True

        for probe in PROBES:
            if _stopped or SENTINEL.exists():
                break

            healthy = probe_service(probe)

            if healthy:
                if probe.fail_count > 0:
                    log(f"[watchdog] {probe.label()} recovered (was fail={probe.fail_count})")
                probe.fail_count = 0
                extra_sleep = 0
                continue

            all_healthy_this_cycle = False
            probe.fail_count += 1
            log(f"[watchdog] {probe.label()} DOWN (fail={probe.fail_count}) — {probe.url}")

            if probe.fail_count <= 2:
                # Tier 1: restart the individual service
                recovered = restart_service(probe)
                if recovered:
                    log(f"[watchdog] {probe.label()} recovered after Tier 1 restart")
                    probe.fail_count = 0
                else:
                    log(f"[watchdog] {probe.label()} still down after Tier 1")

            elif probe.fail_count == 3:
                # Tier 2: full stack restart
                log(f"[watchdog] {probe.label()} fail={probe.fail_count} — Tier 2 full restart")
                recovered = restart_all()
                if recovered:
                    log("[watchdog] all services recovered after Tier 2 full restart")
                    for p in PROBES:
                        p.fail_count = 0
                    extra_sleep = 0
                else:
                    log("[watchdog] stack still unhealthy after Tier 2")

            elif probe.fail_count == 4:
                # Tier 3: Claude Agent SDK diagnostic
                log(f"[watchdog] {probe.label()} fail={probe.fail_count} — Tier 3 SDK escalation")
                escalate_to_sdk(probe)
                # Re-probe after SDK session
                if probe_service(probe):
                    log(f"[watchdog] {probe.label()} recovered after Tier 3 SDK session")
                    probe.fail_count = 0
                else:
                    log(f"[watchdog] {probe.label()} still down after Tier 3")

            else:
                # Backoff: exponential up to MAX_BACKOFF
                write_report(probe)
                extra_sleep = min(extra_sleep * 2 + 30, MAX_BACKOFF)
                log(f"[watchdog] {probe.label()} persists (fail={probe.fail_count}) — extra sleep {extra_sleep}s")

        if not _stopped and all_healthy_this_cycle and cycle % HEARTBEAT_EVERY == 0:
            log(f"[watchdog] all healthy (cycle={cycle})")

        if not _stopped:
            sleep_for = PROBE_INTERVAL + extra_sleep
            _interruptible_sleep(sleep_for)

    log("[watchdog] stopped")


if __name__ == "__main__":
    main()
