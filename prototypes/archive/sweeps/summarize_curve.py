"""Auto-summarize an acceptance CSV: direction, extrema, span, invertible regions.

Replaces hand-reading each curve (PLAN.md Phase 3, item 4). Reads the tidy CSV
that `assemble_curve.py` writes and, for every measure column, prints:

  * direction   -- monotonic increasing / decreasing / flat / non-monotonic,
                   judged with a noise tolerance (real bounces wobble)
  * strict      -- the same call with zero tolerance, so noise stays visible
  * extrema     -- min and max, and the x where each sits
  * span        -- max - min
  * invertible  -- the largest contiguous STRICTLY monotonic runs in x, i.e. the
                   regions where "target measure -> knob value" has one answer
  * predicted   -- whether the observed direction matches the sweep's
                   `predicted_direction`, auto-discovered from the
                   `*.params.json` sidecars sitting next to the CSV

Why a tolerance: crest on a real bounce jitters by a few tenths of a dB. With
zero tolerance every real curve reads "non-monotonic". The default tolerance is
10% of the measure's own span (`--tol-frac`); pass `--tol` for an absolute one
(e.g. a measured crest error bar from Phase 4).

Stdlib only. Measure columns are auto-detected: anything that is not
`index`, `requested_value`, `true_value`, or `value_string`.

Examples:
    # every measure column, x = true_value
    uv run python sweeps/summarize_curve.py \\
        --csv sweeps/out/snts_kick_clip_thresh_v1/snts_kick_clip_thresh_v1.acceptance.csv

    # just crest, with an absolute noise band of 0.3 dB
    uv run python sweeps/summarize_curve.py \\
        --csv sweeps/out/snts_kick_transient_attack_v1/snts_kick_transient_attack_v1.acceptance.csv \\
        --y crest_db --tol 0.3
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

FIXED_COLS = ("index", "requested_value", "true_value", "value_string")


def _num(text: str | None) -> float | None:
    """Parse a CSV cell as a float, or None if it is blank / not a number."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _g(value: float) -> str:
    return f"{value:.6g}"


def _base_name(col: str) -> str:
    """Normalize a measure name so `crest_db` and `crest` compare equal."""
    name = col.strip().lower()
    if name.endswith("_db") and name != "_db":
        name = name[:-3]
    return name


def _discover_prediction(csv_path: Path) -> tuple[str | None, str | None]:
    """Read predicted_measure / predicted_direction from a sidecar next to the CSV."""
    for sidecar in sorted(csv_path.parent.glob("*.params.json")):
        try:
            data = json.loads(sidecar.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        measure = data.get("predicted_measure")
        direction = data.get("predicted_direction")
        if measure or direction:
            return measure, direction
    return None, None


def _classify(diffs: list[float], tol: float) -> tuple[str, list[int]]:
    """Direction verdict plus the collapsed sequence of significant step signs."""
    signs: list[int] = []
    for d in diffs:
        sign = 1 if d > tol else (-1 if d < -tol else 0)
        if sign and (not signs or signs[-1] != sign):
            signs.append(sign)
    ups = any(s > 0 for s in signs)
    downs = any(s < 0 for s in signs)
    if not ups and not downs:
        return "flat", signs
    if ups and not downs:
        return "monotonic INCREASING", signs
    if downs and not ups:
        return "monotonic DECREASING", signs
    turns = len(signs) - 1
    shape = "humped (single peak)" if signs == [1, -1] else (
        "valley (single trough)" if signs == [-1, 1] else f"{turns} turning points"
    )
    return f"non-monotonic: {shape}", signs


def _strict_runs(ys: list[float]) -> list[tuple[int, int, int]]:
    """Maximal runs of consecutive strictly monotone steps as (start, end, sign)."""
    runs: list[tuple[int, int, int]] = []
    start = 0
    prev_sign = 0
    for i in range(len(ys) - 1):
        d = ys[i + 1] - ys[i]
        sign = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign == 0:
            if prev_sign:
                runs.append((start, i, prev_sign))
            start = i + 1
            prev_sign = 0
            continue
        if prev_sign and sign != prev_sign:
            runs.append((start, i, prev_sign))
            start = i
        prev_sign = sign
    if prev_sign:
        runs.append((start, len(ys) - 1, prev_sign))
    return runs


def summarize_column(
    col: str,
    xs: list[float],
    ys: list[float],
    x_name: str,
    tol_frac: float,
    tol_abs: float | None,
    predicted_measure: str | None,
    predicted_direction: str | None,
    skipped: int,
) -> list[str]:
    """Render the summary block for one measure column."""
    lines: list[str] = []
    if len(ys) < 2:
        return [f"{col}: insufficient data (need >=2 measured points)"]

    lo, hi = min(ys), max(ys)
    span = hi - lo
    x_at_min = xs[ys.index(lo)]
    x_at_max = xs[ys.index(hi)]
    diffs = [b - a for a, b in zip(ys, ys[1:])]
    tol = tol_abs if tol_abs is not None else tol_frac * span

    verdict, _ = _classify(diffs, tol)
    strict, _ = _classify(diffs, 0.0)
    noise = [d for d in diffs if 0 < abs(d) <= tol]

    lines.append(f"{col}  ({len(ys)} pts vs {x_name}" + (f", {skipped} unmeasured" if skipped else "") + ")")
    tol_note = f"tol={_g(tol)}" + ("" if tol_abs is not None else f" = {tol_frac:.0%} of span")
    lines.append(f"  direction : {verdict}   [{tol_note}]")
    if strict != verdict:
        lines.append(f"  strict    : {strict}   [tol=0; {len(noise)} step(s) inside the tolerance band]")
    lines.append(f"  min       : {_g(lo)} @ {x_name}={_g(x_at_min)}")
    lines.append(f"  max       : {_g(hi)} @ {x_name}={_g(x_at_max)}")
    lines.append(f"  span      : {_g(span)}")

    runs = _strict_runs(ys)
    if not runs:
        lines.append("  invertible: none (no strictly monotone step)")
    else:
        ranked = sorted(runs, key=lambda r: abs(ys[r[1]] - ys[r[0]]), reverse=True)
        best = abs(ys[ranked[0][1]] - ys[ranked[0][0]])
        shown = [r for r in ranked[:3] if best == 0 or abs(ys[r[1]] - ys[r[0]]) >= 0.5 * best]
        for n, (i, j, sign) in enumerate(shown):
            arrow = "up" if sign > 0 else "down"
            tag = "  <- largest" if n == 0 else ""
            label = "  invertible:" if n == 0 else "             "
            lines.append(
                f"{label} {_g(xs[i])}..{_g(xs[j])} -> {_g(ys[i])}..{_g(ys[j])}"
                f"  ({arrow}, {j - i + 1} pts, dy={_g(abs(ys[j] - ys[i]))}){tag}"
            )

    if predicted_direction and predicted_measure and _base_name(predicted_measure) == _base_name(col):
        want = predicted_direction.strip().lower()
        got = verdict.lower()
        if "non-monotonic" in got:
            call = "PARTIAL (non-monotonic overall; check the invertible region)"
        elif want.startswith("inc"):
            call = "MATCH" if "increasing" in got else "MISMATCH"
        elif want.startswith("dec"):
            call = "MATCH" if "decreasing" in got else "MISMATCH"
        elif want.startswith("flat"):
            call = "MATCH" if got == "flat" else "MISMATCH"
        else:
            call = "UNKNOWN predicted_direction"
        lines.append(f"  predicted : {predicted_measure} {predicted_direction}  ->  {call}")

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="Acceptance CSV from assemble_curve.py.")
    parser.add_argument("--x", default="true_value", help="Independent column (default true_value).")
    parser.add_argument("--y", nargs="*", default=None, help="Measure columns (default: all detected).")
    parser.add_argument("--tol-frac", type=float, default=0.10,
                        help="Noise band as a fraction of each column's span (default 0.10).")
    parser.add_argument("--tol", type=float, default=None,
                        help="Absolute noise band; overrides --tol-frac for every column.")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"No rows in {csv_path}")

    header = list(rows[0].keys())
    if args.x not in header:
        raise SystemExit(f"--x {args.x!r} not in columns: {', '.join(header)}")

    detected = [c for c in header if c not in FIXED_COLS and c != args.x]
    wanted = args.y if args.y else detected
    missing = [c for c in wanted if c not in header]
    if missing:
        raise SystemExit(f"Column(s) not in CSV: {', '.join(missing)}. Have: {', '.join(header)}")

    predicted_measure, predicted_direction = _discover_prediction(csv_path)

    print(f"CSV : {csv_path}")
    print(f"x   : {args.x}   rows: {len(rows)}")
    if predicted_measure or predicted_direction:
        print(f"spec: predicted {predicted_measure} {predicted_direction} (from *.params.json sidecars)")
    else:
        print("spec: no predicted_direction found next to this CSV")
    print(f"cols: {', '.join(wanted) if wanted else '(none detected)'}")

    for col in wanted:
        pairs = [(_num(r.get(args.x)), _num(r.get(col))) for r in rows]
        clean = [(x, y) for x, y in pairs if x is not None and y is not None]
        skipped = len(pairs) - len(clean)
        clean.sort(key=lambda t: t[0])
        xs = [x for x, _ in clean]
        ys = [y for _, y in clean]
        print()
        for line in summarize_column(col, xs, ys, args.x, args.tol_frac, args.tol,
                                     predicted_measure, predicted_direction, skipped):
            print(line)


if __name__ == "__main__":
    main()
