"""Assemble the acceptance curve from a sweep's sidecars (+ optional lab pass).

Reads every `*.params.json` sidecar in a sweep output directory and joins them
into one tidy table `{index, requested_value, true_value, <measures...>}`. If a
bounce WAV exists next to a sidecar and a runnable `ears` is available, it calls
`ears analyze <wav> --json` to fill the measure columns; otherwise it leaves them
from the sidecar's own `measure` field (or blank).

Finally it reports whether the swept parameter vs the predicted measure is
monotonic — that single clean (or cleanly reversed) curve is the spike's
milestone (§5 acceptance).

READING GOTCHA — do NOT pipe the raw CSV through `column -t`.
    For VST params `value_string` is EMPTY, so `column -t` collapses the missing
    field and every measure column shifts one to the left. You will misread the
    data. Every CSV field is now written quoted (csv.QUOTE_ALL) so blanks show up
    as `""`, and a pre-aligned human view is written alongside as
    `<sweep_id>.acceptance.txt`. Read the `.txt`, or parse the CSV with a real
    CSV reader. Never `column -t` the CSV.

Examples:
    # curve from sidecars only (no lab); prints the table + monotonicity verdict
    uv run python sweeps/assemble_curve.py --dir sweeps/out/roar_drive_v1

    # run the lab per bounce to fill measures, pulling two keys from ears JSON
    uv run python sweeps/assemble_curve.py --dir sweeps/out/kick_pitch_v1 \\
        --ears-cmd "uv run --project /path/to/ears ears" \\
        --measure-keys sub_share crest
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any


def _dig(obj: Any, dotted: str) -> Any:
    """Fetch a possibly-nested key like 'measures.sub_share' from a dict."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _run_ears(ears_cmd: str, wav: Path, extra: list[str]) -> dict[str, Any] | None:
    argv = shlex.split(ears_cmd) + ["analyze", str(wav), "--json", *extra]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        print(f"  ears timed out on {wav.name}")
        return None
    if proc.returncode != 0:
        print(f"  ears failed on {wav.name}: {proc.stderr.strip()[-200:]}")
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"  could not parse ears output for {wav.name}")
        return None


def _monotonic(pairs: list[tuple[float, float]]) -> str:
    """Classify a list of (x, y) by direction, ignoring None ys."""
    clean = [(x, y) for x, y in pairs if y is not None]
    if len(clean) < 2:
        return "insufficient data (need >=2 measured points)"
    clean.sort(key=lambda t: t[0])
    ys = [y for _, y in clean]
    diffs = [b - a for a, b in zip(ys, ys[1:])]
    inc = all(d >= 0 for d in diffs)
    dec = all(d <= 0 for d in diffs)
    if inc and not dec:
        return "monotonic INCREASING"
    if dec and not inc:
        return "monotonic DECREASING"
    if inc and dec:
        return "flat"
    return "non-monotonic"


def _resolve_measure_col(predicted: str | None, measure_cols: list[str]) -> str | None:
    """Map a predicted measure name to the actual column that holds it.

    The spec often names the measure loosely (e.g. 'crest') while the measurer
    emits a suffixed column ('crest_db'). Match exact first, then prefix, then a
    contains-match, so the monotonicity verdict actually fires instead of the old
    'no measured column' false negative.
    """
    if not predicted:
        return None
    if predicted in measure_cols:
        return predicted
    for c in measure_cols:
        if c.startswith(predicted) or predicted.startswith(c):
            return c
    for c in measure_cols:
        if predicted in c or c in predicted:
            return c
    return None


def _suggest_refine(pairs: list[tuple[float, float]]) -> str | None:
    """For a non-monotonic curve, locate the interior extremum and propose a
    finer sweep window around it (the 'sweep the hump, not the ends' lesson,
    automated)."""
    clean = sorted([(x, y) for x, y in pairs if y is not None], key=lambda t: t[0])
    if len(clean) < 3:
        return None
    xs = [x for x, _ in clean]
    ys = [y for _, y in clean]
    # interior index of the global max and min
    imax = max(range(len(ys)), key=lambda i: ys[i])
    imin = min(range(len(ys)), key=lambda i: ys[i])
    # pick whichever extremum is interior (not at an endpoint)
    idx = None
    kind = ""
    if 0 < imax < len(ys) - 1:
        idx, kind = imax, "peak"
    elif 0 < imin < len(ys) - 1:
        idx, kind = imin, "trough"
    if idx is None:
        return None
    lo = xs[idx - 1]
    hi = xs[idx + 1]
    span = hi - lo
    steps = 13
    return (f"non-monotonic {kind} near x={xs[idx]:.4g} (y={ys[idx]:.4g}). "
            f"Suggested finer sweep: start={lo:.4g} stop={hi:.4g} steps={steps} "
            f"(~{span / (steps - 1):.4g}/step) to resolve it.")


def _fmt_cell(value: Any) -> str:
    """Render one value for the fixed-width view; blanks stay visible as '-'."""
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _write_wide(
    path: Path,
    cols: list[str],
    rows: list[dict[str, Any]],
    header_lines: list[str],
) -> None:
    """Write a fixed-width, right-aligned view that `column -t` cannot shift.

    Empty cells become '-' so a missing `value_string` (every VST param) is
    impossible to mistake for a shifted column.
    """
    table = [[_fmt_cell(r.get(c)) for c in cols] for r in rows]
    widths = [
        max(len(cols[i]), *(len(row[i]) for row in table)) if table else len(cols[i])
        for i in range(len(cols))
    ]

    def line(cells: list[str]) -> str:
        return "  ".join(cell.rjust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    out: list[str] = [f"# {h}" for h in header_lines]
    out.append("# empty cell = '-'  (VST params have no value_string)")
    out.append("")
    out.append(line(cols))
    out.append("  ".join("-" * w for w in widths))
    out.extend(line(row) for row in table)
    path.write_text("\n".join(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, help="Sweep output directory with *.params.json sidecars.")
    parser.add_argument("--ears-cmd", default=None, help="Command to invoke ears (e.g. 'ears' or 'uv run ears').")
    parser.add_argument("--measure-keys", nargs="*", default=[], help="Dotted keys to pull from ears JSON.")
    parser.add_argument("--ears-arg", nargs="*", default=[], help="Extra args passed to `ears analyze`.")
    parser.add_argument("--out", default=None, help="CSV output path (default <dir>/<sweep_id>.acceptance.csv).")
    args = parser.parse_args()

    out_dir = Path(args.dir)
    sidecars = sorted(out_dir.glob("*.params.json"))
    if not sidecars:
        raise SystemExit(f"No *.params.json sidecars in {out_dir}")

    rows: list[dict[str, Any]] = []
    sweep_id = "sweep"
    predicted_measure = None
    predicted_direction = None

    for sc in sidecars:
        data = json.loads(sc.read_text())
        sweep_id = data.get("sweep_id", sweep_id)
        predicted_measure = data.get("predicted_measure", predicted_measure)
        predicted_direction = data.get("predicted_direction", predicted_direction)

        row: dict[str, Any] = {
            "index": data.get("index"),
            "requested_value": data.get("requested_value"),
            "true_value": data.get("true_value"),
            "value_string": data.get("value_string"),
        }

        measures: dict[str, Any] = {}
        wav_name = data.get("wav") or data.get("bounce")
        wav = (out_dir / wav_name) if wav_name else None

        if args.ears_cmd and wav and wav.exists() and args.measure_keys:
            profile = _run_ears(args.ears_cmd, wav, args.ears_arg)
            if profile is not None:
                for key in args.measure_keys:
                    measures[key.split(".")[-1]] = _dig(profile, key)

        if not measures:
            # Fall back to whatever the sidecar already recorded.
            if data.get("measure") is not None:
                measures[predicted_measure or "measure"] = data.get("measure")

        row.update(measures)
        rows.append(row)

    # Column order: fixed fields first, then any measure columns discovered.
    fixed = ["index", "requested_value", "true_value", "value_string"]
    measure_cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in fixed and k not in measure_cols:
                measure_cols.append(k)
    cols = fixed + measure_cols

    out_path = Path(args.out) if args.out else out_dir / f"{sweep_id}.acceptance.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # QUOTE_ALL: a blank `value_string` must stay visible as `""` so nobody can
    # eyeball the raw CSV and silently read a shifted column.
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c) for c in cols})

    # Resolve the predicted measure ('crest') to its real column ('crest_db')
    # so the verdict actually fires instead of a false 'no measured column'.
    resolved_col = _resolve_measure_col(predicted_measure, measure_cols)
    verdict = None
    pairs: list[tuple[Any, Any]] | None = None
    if resolved_col:
        pairs = [(r["true_value"], r.get(resolved_col)) for r in rows]
        verdict = _monotonic(pairs)
    refine = _suggest_refine(pairs) if (pairs is not None and verdict == "non-monotonic") else None

    header_lines = [f"sweep: {sweep_id}", f"rows: {len(rows)}", f"csv: {out_path.name}"]
    if predicted_measure:
        header_lines.append(f"predicted: {predicted_measure} {predicted_direction}")
    if verdict:
        col_note = "" if resolved_col == predicted_measure else f" (column: {resolved_col})"
        header_lines.append(f"observed: {verdict}{col_note}")
    if refine:
        header_lines.append(f"refine: {refine}")

    wide_path = out_path.with_suffix(".txt")
    _write_wide(wide_path, cols, rows, header_lines)

    print(f"Sweep: {sweep_id}")
    print(f"Rows:  {len(rows)}  ->  {out_path}")
    print("Columns:", ", ".join(cols))
    print(f"Aligned view: {wide_path}   <- read THIS by eye; do NOT `column -t` the CSV")

    if verdict:
        col_note = "" if resolved_col == predicted_measure else f"   (measured column: {resolved_col})"
        print(f"\nPredicted: {predicted_measure} {predicted_direction}")
        print(f"Observed:  {verdict}{col_note}")
        if refine:
            print(f"Refine:    {refine}")
    else:
        print(f"\nNo measured column for predicted measure {predicted_measure!r} yet "
              "-- hand the bounces to a live `ears` and re-run with --ears-cmd/--measure-keys.")


if __name__ == "__main__":
    main()
