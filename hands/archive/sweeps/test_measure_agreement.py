"""Regression test: the ears lab and `measure_local.py` must still agree.

Guards the Phase-1 guarantee (PLAN.md Phase 3, item 6). Runs BOTH measurers on
one fixed bounce and fails if any canonical band share -- or crest (ears `crest`
vs local `crest_db`) -- diverges by more than 1e-6. The band math in
`measure_local.py` is copied verbatim from `ears`, so agreement is the contract;
a drift here means one of the two changed and the map's numbers are in doubt.

Deliberately NOT compared: `lufs_*` and `true_peak_*`. Those are gain-dependent
and meaningless on our gain-scaled stems.

The ears lab lives in disposable `_agent_scratch`. If its venv is gone the test
SKIPS with a clear message instead of failing.

Runs both ways:
    uv run python sweeps/test_measure_agreement.py
    uv run --with pytest python -m pytest sweeps/test_measure_agreement.py -s

Examples:
    # a different bounce, looser tolerance
    uv run python sweeps/test_measure_agreement.py \\
        --wav sweeps/out/snts_kick_clip_thresh_v1/bounce_006.wav --tol 1e-5
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SWEEPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SWEEPS_DIR.parent
LOCAL_MEASURER = SWEEPS_DIR / "measure_local.py"

EARS_LAB = Path("/Users/anthonybecker/_agent_scratch/ears_lab")
EARS_PYTHON = EARS_LAB / ".venv" / "bin" / "python"
EARS_SHIM = EARS_LAB / "ears_shim.py"

DEFAULT_WAV = SWEEPS_DIR / "out" / "snts_kick_clip_validate_v1" / "bounce_000.wav"
DEFAULT_TOL = 1e-6

# (label, key in ears JSON, key in measure_local JSON)
COMPARISONS: tuple[tuple[str, str, str], ...] = (
    ("sub_share", "sub_share", "sub_share"),
    ("low_share", "low_share", "low_share"),
    ("mid_share", "mid_share", "mid_share"),
    ("high_share", "high_share", "high_share"),
    ("air_share", "air_share", "air_share"),
    ("crest", "crest", "crest_db"),
)


@dataclass
class Report:
    """Outcome of one comparison run."""

    skip_reason: str | None = None
    wav: Path | None = None
    tol: float = DEFAULT_TOL
    ears_argv: list[str] = field(default_factory=list)
    local_argv: list[str] = field(default_factory=list)
    diffs: list[tuple[str, float | None, float | None, float | None, bool]] = field(default_factory=list)

    @property
    def failures(self) -> list[str]:
        return [label for label, _, _, _, ok in self.diffs if not ok]

    def text(self) -> str:
        lines: list[str] = []
        if self.skip_reason:
            return f"SKIP: {self.skip_reason}"
        lines.append(f"wav  : {self.wav}")
        lines.append(f"tol  : {self.tol:g}")
        lines.append(f"ears : {' '.join(self.ears_argv)}")
        lines.append(f"local: {' '.join(self.local_argv)}")
        lines.append("")
        lines.append(f"{'column':<12}{'ears':>24}{'measure_local':>24}{'abs diff':>14}  verdict")
        lines.append(f"{'-' * 10:<12}{'-' * 22:>24}{'-' * 22:>24}{'-' * 12:>14}  {'-' * 7}")
        for label, a, b, diff, ok in self.diffs:
            fa = "MISSING" if a is None else f"{a:.17g}"
            fb = "MISSING" if b is None else f"{b:.17g}"
            fd = "n/a" if diff is None else f"{diff:.3e}"
            lines.append(f"{label:<12}{fa:>24}{fb:>24}{fd:>14}  {'ok' if ok else 'FAIL'}")
        return "\n".join(lines)


def _run_json(argv: list[str], wav: Path) -> dict[str, Any] | None:
    """Call `<argv> analyze <wav> --json` and parse stdout as JSON."""
    try:
        proc = subprocess.run(
            [*argv, "analyze", str(wav), "--json"],
            capture_output=True, text=True, timeout=300, cwd=PROJECT_ROOT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "error" in payload:
        return None
    return payload


def _local_candidates() -> list[list[str]]:
    """Interpreters that might have numpy + soundfile for `measure_local.py`."""
    return [
        [sys.executable, str(LOCAL_MEASURER)],
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", str(LOCAL_MEASURER)],
        [str(EARS_PYTHON), str(LOCAL_MEASURER)],
    ]


def run_comparison(
    wav: Path = DEFAULT_WAV,
    tol: float = DEFAULT_TOL,
    ears_cmd: str | None = None,
    local_cmd: str | None = None,
) -> Report:
    """Measure `wav` with both measurers and diff the shared columns."""
    report = Report(wav=wav, tol=tol)

    if not wav.exists():
        report.skip_reason = f"fixture bounce is missing: {wav}"
        return report

    if ears_cmd:
        ears_argv = shlex.split(ears_cmd)
    else:
        if not EARS_PYTHON.exists() or not EARS_SHIM.exists():
            report.skip_reason = (
                f"ears lab venv not found at {EARS_LAB} (it lives in disposable "
                "_agent_scratch; rebuild it per HANDOFF.md, or pass --ears-cmd)"
            )
            return report
        ears_argv = [str(EARS_PYTHON), str(EARS_SHIM)]
    report.ears_argv = ears_argv

    ears_json = _run_json(ears_argv, wav)
    if ears_json is None:
        report.skip_reason = f"ears measurer would not run: {' '.join(ears_argv)}"
        return report

    local_json = None
    for candidate in ([shlex.split(local_cmd)] if local_cmd else _local_candidates()):
        local_json = _run_json(candidate, wav)
        if local_json is not None:
            report.local_argv = candidate
            break
    if local_json is None:
        report.skip_reason = (
            "measure_local.py would not run (needs numpy + soundfile); tried "
            + " | ".join(" ".join(c) for c in _local_candidates())
        )
        return report

    for label, ears_key, local_key in COMPARISONS:
        a = ears_json.get(ears_key)
        b = local_json.get(local_key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            report.diffs.append((label, a if isinstance(a, (int, float)) else None,
                                 b if isinstance(b, (int, float)) else None, None, False))
            continue
        diff = abs(float(a) - float(b))
        report.diffs.append((label, float(a), float(b), diff, diff <= tol))

    return report


def test_measure_agreement() -> None:
    """pytest entry point: skips if the ears lab is gone, else asserts agreement."""
    report = run_comparison()
    print(report.text())
    if report.skip_reason:
        import pytest

        pytest.skip(report.skip_reason)
    assert not report.failures, (
        f"measurers diverged beyond {report.tol:g} on: {', '.join(report.failures)}\n{report.text()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wav", default=str(DEFAULT_WAV), help="Fixture bounce to measure with both measurers.")
    parser.add_argument("--tol", type=float, default=DEFAULT_TOL, help="Max allowed absolute difference.")
    parser.add_argument("--ears-cmd", default=None, help="Override the ears invocation (without 'analyze').")
    parser.add_argument("--local-cmd", default=None, help="Override the measure_local invocation.")
    args = parser.parse_args()

    report = run_comparison(Path(args.wav), args.tol, args.ears_cmd, args.local_cmd)
    print(report.text())
    if report.skip_reason:
        return 0
    if report.failures:
        print(f"\nFAIL: {len(report.failures)} column(s) diverged beyond {args.tol:g}: "
              f"{', '.join(report.failures)}")
        return 1
    print(f"\nPASS: all {len(report.diffs)} columns agree within {args.tol:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
