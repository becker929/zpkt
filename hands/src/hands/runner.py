"""MCP Step Runner — executes a list[Step] against a transport.

Provides retry logic, rollback on error, and interactive prompts for manual steps.
Tracks partial execution state so runs can be resumed from a specific step index.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from hands.codegen import Step


@dataclass
class StepResult:
    """Execution record for one step."""

    index: int
    label: str
    status: Literal["ok", "skipped", "manual", "error", "aborted"]
    result: Any = None
    error: str | None = None
    retried: bool = False


class ManualPolicy(Enum):
    PROMPT = "prompt"
    SKIP = "skip"
    FAIL = "fail"


_TIMEOUT_SIGNAL = "Cannot reach Ableton"


class StepRunner:
    """Executes a list[Step] sequentially against a transport.

    The transport must implement ``execute(code: str) -> dict``.
    On error the runner calls ``song.undo()`` via transport, optionally
    retries, then stops the pipeline.

    Resumability::

        results = runner.execute(steps, resume_from=14)
    """

    def __init__(
        self,
        transport: Any,
        retry_count: int = 1,
        retry_delay: float = 5.0,
    ) -> None:
        self._transport = transport
        self._retry_count = retry_count
        self._retry_delay = retry_delay

    def execute(
        self,
        steps: list[Step],
        on_manual: ManualPolicy = ManualPolicy.PROMPT,
        resume_from: int = 0,
    ) -> list[StepResult]:
        """Execute *steps* sequentially and return per-step results."""
        results: list[StepResult] = []

        for i, step in enumerate(steps):
            if i < resume_from:
                results.append(StepResult(index=i, label=step.label, status="skipped"))
                continue

            print(f"\n[{i:2d}/{len(steps) - 1}] {step.label}")

            if step.note is not None:
                result = self._handle_manual(i, step, on_manual)
            else:
                result = self._execute_step(i, step)

            results.append(result)

            if result.status in ("error", "aborted"):
                print(f"  Pipeline stopped at step {i}. "
                      f"Resume with --resume {i} after fixing the issue.")
                break

        return results

    def _handle_manual(
        self, index: int, step: Step, policy: ManualPolicy,
    ) -> StepResult:
        print(f"  MANUAL — {step.note}")

        if policy is ManualPolicy.PROMPT:
            input("  Press Enter when done...")
            mcp = self._transport.execute(step.code)
            return StepResult(index=index, label=step.label, status="manual",
                              result=mcp.result)

        if policy is ManualPolicy.SKIP:
            print("  Skipping (SKIP policy).")
            return StepResult(index=index, label=step.label, status="skipped")

        raise RuntimeError(
            f"Manual step {index} ({step.label!r}) cannot be automated. "
            f"Note: {step.note}"
        )

    def _execute_step(self, index: int, step: Step) -> StepResult:
        for attempt in range(self._retry_count + 1):
            mcp = self._transport.execute(step.code)

            if mcp.status == "ok":
                if mcp.result is not None:
                    print(f"  → {mcp.result}")
                return StepResult(
                    index=index, label=step.label, status="ok",
                    result=mcp.result, retried=(attempt > 0),
                )

            error_str = str(mcp.error or mcp.result or "unknown error")

            if _TIMEOUT_SIGNAL in error_str:
                if attempt < self._retry_count:
                    print(f"  timeout — waiting {self._retry_delay}s then retrying...")
                    time.sleep(self._retry_delay)
                    continue
                return StepResult(
                    index=index, label=step.label, status="aborted",
                    error=f"Ableton unreachable after {attempt + 1} attempt(s): {error_str}",
                )

            print(f"  error (attempt {attempt + 1}): {error_str}")
            self._attempt_undo()


            if attempt < self._retry_count:
                print(f"  retrying step {index}...")
                continue

            return StepResult(
                index=index, label=step.label, status="error",
                error=error_str, retried=(attempt > 0),
            )

        return StepResult(index=index, label=step.label, status="aborted",
                          error="retry loop exited unexpectedly")

    def _attempt_undo(self) -> None:
        try:
            self._transport.execute("song.undo()")
        except Exception as exc:
            print(f"  WARNING: undo() failed: {exc}")
