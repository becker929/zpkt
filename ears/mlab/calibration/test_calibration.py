"""pytest wrapper: one test per known-answer row."""
import pytest

import checks

ROWS = checks.run_all(crosscheck=False)


@pytest.mark.parametrize("r", ROWS, ids=[f"{r['instrument']}::{r['case']}" for r in ROWS])
def test_known_answer(r):
    assert r["ok"], f"expected {r['expected']} (±{r['tol']}), measured {r['measured']}"
