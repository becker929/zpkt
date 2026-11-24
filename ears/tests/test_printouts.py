"""printouts: the formatting rules the reports rely on, checked without running an instrument."""

from __future__ import annotations

from mlab import printouts


def test_number_never_prints_minus_zero() -> None:
    assert printouts.number(-0.04) == "+0.0"
    assert printouts.number(-0.04, "{:.2f}") == "-0.04"
    assert printouts.number(-0.001, "{:.2f}") == "0.00"
    assert printouts.number(None) == "-" and printouts.number(None, none="n/a") == "n/a"


def test_range_row_flags_outside() -> None:
    g = {"mix": -3.0, "mean": -1.0, "min": -2.0, "max": 0.0, "diff": -2.0, "outside": -1.0}
    assert printouts.range_row("sub", g).endswith("  <")
    assert printouts.range_row("sub", {**g, "outside": 0.0}).endswith("+0.0")
    assert printouts.range_row("sub", None) == "  sub                              -"
    assert printouts.refs_text(1) == "1 reference" and printouts.refs_text(2) == "2 references"


def test_peaks_report_without_peaks_stops_after_structure() -> None:
    an = {
        "bpm": 160.0,
        "bars": 8,
        "main_break": None,
        "peak_bars": None,
        "drop_vs_peak_high_db": None,
        "peak_after_main_break": False,
    }
    result, lines = printouts.peaks_report("TARGET x", (an, None), {"ref": (an, None)})
    assert result == {"structure": {"TARGET x": an, "ref": an}}
    assert lines[-1] == "ref                 160.00     8  None        None                    -  False"
