"""Claude Code as an engine: one `claude -p` process per turn, its stream-json translated into page events.

Claude is resumed by the session's id (`--resume`), or by the id the turn names after a compaction started it afresh. The sign-in token comes only from the secret lookup the app is
given (the Keychain, through the harness's `secret`); this module never reads a key or a file of keys itself.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from zpkt.app.ask.engines import claude_command
from zpkt.app.ask.events import ClaudeStream
from zpkt.app.ask.provider import Emit, Outcome, Turn

AUTH_FAIL = re.compile(
    r"Failed to authenticate|Invalid API key|OAuth (session|token) (has )?expired|Please run /login|not logged in", re.I
)
AUTH_HELP = (
    "Claude Code is not signed in on the Mac, so it cannot answer. Switch the agent to Gemini, or sign Claude in: "
    "run `claude setup-token` and store the token in the Keychain as zpkt-claude-oauth, then ask again. "
    "Or run `claude` in Terminal and use /login."
)
NOISE = re.compile(r"^\[STARTUP\]|256-color support|Ripgrep is not available|YOLO mode is enabled|^\s*$")
KILL_AFTER_S = 5.0

Secret = Callable[[str], str | None]


def find_claude(environ: Mapping[str, str], home: Path) -> str:
    if environ.get("CLAUDE_BIN"):
        return environ["CLAUDE_BIN"]
    local = home / ".local" / "bin" / "claude"
    return str(local) if local.exists() else "claude"


class ClaudeProvider:
    engine = "claude"

    def __init__(
        self,
        secret: Secret,
        claude_bin: str | None = None,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> None:
        self.secret = secret
        self.environ = dict(os.environ if environ is None else environ)
        self.home = home or Path.home()
        self.bin = claude_bin or find_claude(self.environ, self.home)
        self.signed_out_at = 0.0  # when Claude last said it is not signed in (cleared when it answers)

    def available(self) -> dict[str, Any]:
        return {"id": "claude", "name": "Claude Code", "bin": self.bin}

    def run(self, turn: Turn, emit: Emit, cancel: threading.Event) -> Outcome:
        token = self.secret("oauth") or ""
        cmd = claude_command(
            prompt=turn.prompt,
            mode=turn.mode,
            model=turn.model,
            resume=turn.resume,
            session_id=turn.engine_session or turn.session["id"],
            claude_bin=self.bin,
            environ=self.environ,
            home=self.home,
            token=token,
            system=turn.system,
            extra_dirs=turn.extra_dirs,
            tools=turn.tools,
        )
        try:
            proc = subprocess.Popen(
                [cmd.bin, *cmd.args],
                cwd=turn.session["cwd"],
                env=cmd.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            return Outcome(None, None, str(exc))
        auth_failed = threading.Event()
        threads = [
            threading.Thread(target=self._stdout, args=(proc, turn, emit, auth_failed), daemon=True),
            threading.Thread(target=self._stderr, args=(proc, emit, auth_failed), daemon=True),
        ]
        for t in threads:
            t.start()
        assert proc.stdin
        try:
            proc.stdin.write(cmd.stdin or "")
            proc.stdin.close()
        except OSError:
            pass
        stopped = self._wait(proc, cancel)
        for t in threads:
            t.join(timeout=5)
        code = proc.returncode
        sig = "SIGTERM" if stopped else (signal.Signals(-code).name if code is not None and code < 0 else None)
        if auth_failed.is_set():
            self.signed_out_at = time.time()
            emit({"type": "error", "message": AUTH_HELP})
            return Outcome(code or 1, sig)
        return Outcome(code, sig)

    def _wait(self, proc: subprocess.Popen[str], cancel: threading.Event) -> bool:
        """Wait for the process; end it if `cancel` is set. True when it was stopped."""
        while True:
            try:
                proc.wait(timeout=0.1)
                return False
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=KILL_AFTER_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    return True

    def _stdout(self, proc: subprocess.Popen[str], turn: Turn, emit: Emit, auth_failed: threading.Event) -> None:
        stream = ClaudeStream()
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip("\n")
            try:
                j = json.loads(line)
            except ValueError:
                if not NOISE.search(line):
                    emit({"type": "log", "text": line})
                continue
            if not isinstance(j, dict):
                continue
            for ev in stream.feed(j):
                if ev["type"] == "tool_use" or (ev["type"] == "result" and (ev.get("stats") or {}).get("total_tokens")):
                    turn.mark_started("")
                if ev["type"] == "message" and ev.get("role") == "user":
                    continue
                # The CLI's own "Failed to authenticate" would read as Claude's answer: the error row says it instead.
                if ev["type"] == "message" and AUTH_FAIL.search(ev.get("content") or ""):
                    auth_failed.set()
                    continue
                emit(ev)

    def _stderr(self, proc: subprocess.Popen[str], emit: Emit, auth_failed: threading.Event) -> None:
        assert proc.stderr
        for line in proc.stderr:
            line = line.rstrip("\n")
            if NOISE.search(line):
                continue
            if AUTH_FAIL.search(line):
                auth_failed.set()
            emit({"type": "log", "stream": "stderr", "text": line})
