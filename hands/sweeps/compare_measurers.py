"""Compare two acceptance CSVs column by column and report the max abs diff.

Used by Phase 1 of PLAN.md to prove the real `ears` lab agrees with the
provisional `measure_local.py` on every sweep, not just on one spot check.

Column aliasing: the ears shim emits `crest`, `measure_local` emits `crest_db`.
They are the same quantity (20*log10(peak/rms)), so they are compared together.

Examples:
    # positional: A (ears) vs B (measure_local)
    python3 sweeps/compare_measurers.py \
        sweeps/out/<id>/<id>.acceptance.ears.csv \
        sweeps/out/<id>/<id>.acceptance.local.csv

    # machine-readable rows, for rolling many sweeps into one table
    python3 sweeps/compare_measurers.py A.csv B.csv --tsv --label <sweep_id>
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

# Columns that mean the same thing under different names.
ALIASES = {"crest_db": "crest"}

# Non-measure columns; compared for identity but not for tolerance.
KEYS = ("index", "requested_value", "true_value", "value_string")


def _load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _canon(name: str) -> str:
    return ALIASES.get(name, name)


def _num(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def compare(a_path: Path, b_path: Path, tol: float) -> tuple[list[tuple[str, int, float]], bool]:
    a_rows, b_rows = _load(a_path), _load(b_path)
    if len(a_rows) != len(b_rows):
        raise SystemExit(f"row count mismatch: {a_path.name}={len(a_rows)} {b_path.name}={len(b_rows)}")

    a_cols = {_canon(c): c for c in (a_rows[0].keys() if a_rows else [])}
    b_cols = {_canon(c): c for c in (b_rows[0].keys() if b_rows else [])}
    shared = [c for c in a_cols if c in b_cols and c not in KEYS]

    results: list[tuple[str, int, float]] = []
    ok = True
    for canon in shared:
        worst, n = 0.0, 0
        for ra, rb in zip(a_rows, b_rows):
            va, vb = _num(ra.get(a_cols[canon])), _num(rb.get(b_cols[canon]))
            if va is None or vb is None:
                continue
            n += 1
            worst = max(worst, abs(va - vb))
        if n == 0:
            continue
        results.append((canon, n, worst))
        if worst > tol:
            ok = False
    return results, ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a", nargs="?", help="First CSV (e.g. the ears-measured one).")
    p.add_argument("b", nargs="?", help="Second CSV (e.g. the measure_local one).")
    p.add_argument("--a", dest="a_flag", default=None, help="Alias for the first positional.")
    p.add_argument("--b", dest="b_flag", default=None, help="Alias for the second positional.")
    p.add_argument("--tol", type=float, default=1e-6)
    p.add_argument("--label", default=None, help="Name to print for this comparison.")
    p.add_argument("--tsv", action="store_true", help="Emit tab-separated rows instead of a table.")
    args = p.parse_args()

    a_raw, b_raw = args.a_flag or args.a, args.b_flag or args.b
    if not a_raw or not b_raw:
        raise SystemExit("need two CSVs: compare_measurers.py A.csv B.csv")

    a_path, b_path = Path(a_raw), Path(b_raw)
    results, ok = compare(a_path, b_path, args.tol)
    label = args.label or a_path.parent.name

    if args.tsv:
        for canon, n, worst in results:
            print(f"{label}\t{canon}\t{n}\t{worst:.3e}\t{'ok' if worst <= args.tol else 'FAIL'}")
    else:
        print(f"{label}  (tol={args.tol:g})")
        print(f"  {'column':<12} {'n':>4} {'max abs diff':>14}  verdict")
        for canon, n, worst in results:
            print(f"  {canon:<12} {n:>4} {worst:>14.3e}  {'ok' if worst <= args.tol else 'FAIL'}")
        print(f"  => {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
