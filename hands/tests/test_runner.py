"""Tests for StepRunner with MockTransport — all offline, no Ableton required."""
from __future__ import annotations

import pytest

from hands.codegen import Step
from hands.runner import ManualPolicy, StepResult, StepRunner
from hands.transport import McpResult, MockTransport


def _steps(n: int) -> list[Step]:
    return [Step(label=f"Step {i}", code=f"result = {i!r}") for i in range(n)]


def test_happy_path_all_ok() -> None:
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(_steps(3))
    assert len(results) == 3
    assert all(r.status == "ok" for r in results)


def test_resume_skips_first_n_steps() -> None:
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(_steps(4), resume_from=2)
    assert results[0].status == "skipped"
    assert results[1].status == "skipped"
    assert results[2].status == "ok"
    assert results[3].status == "ok"


def test_resume_skipped_steps_not_executed() -> None:
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    runner.execute(_steps(4), resume_from=2)
    assert len(transport.calls) == 2


def test_error_then_ok_marks_retried() -> None:
    responses = [
        McpResult(status="error", error="transient boom"),
        McpResult(status="ok", result="undo ok"),
        McpResult(status="ok", result="success"),
    ]
    transport = MockTransport(responses=responses)
    runner = StepRunner(transport, retry_count=1, retry_delay=0.0)
    results = runner.execute(_steps(1))
    assert results[0].status == "ok"
    assert results[0].retried is True


def test_timeout_abort_after_retries_exhausted() -> None:
    timeout_err = McpResult(status="error", error="Cannot reach Ableton: timed out")
    transport = MockTransport(responses=[timeout_err, timeout_err])
    runner = StepRunner(transport, retry_count=1, retry_delay=0.0)
    results = runner.execute(_steps(1))
    assert results[0].status == "aborted"
    assert "Cannot reach Ableton" in (results[0].error or "")


def test_manual_policy_skip() -> None:
    steps = [Step(label="Manual", code="result = 'ok'", note="do something manually")]
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(steps, on_manual=ManualPolicy.SKIP)
    assert results[0].status == "skipped"


def test_manual_policy_fail_raises_runtime_error() -> None:
    steps = [Step(label="Manual", code="result = 'ok'", note="do something manually")]
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    with pytest.raises(RuntimeError):
        runner.execute(steps, on_manual=ManualPolicy.FAIL)


def test_pipeline_stops_after_first_error() -> None:
    responses = [
        McpResult(status="error", error="hard fail"),
        McpResult(status="ok", result="undo ok"),
    ]
    transport = MockTransport(responses=responses)
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(_steps(4))
    assert len(results) == 1
    assert results[0].status == "error"


def test_step_result_has_correct_index() -> None:
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(_steps(3))
    assert [r.index for r in results] == [0, 1, 2]


def test_non_retried_ok_has_retried_false() -> None:
    transport = MockTransport()
    runner = StepRunner(transport, retry_count=0)
    results = runner.execute(_steps(1))
    assert results[0].retried is False
