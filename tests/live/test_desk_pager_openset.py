"""zpkt.live.desk_pager and openset: the code the app sends to start the pager and to ask which set is open."""

from __future__ import annotations

from pathlib import Path

from zpkt.live import desk_pager, openset
from zpkt.live.testing import FakeLive, hw002_like

PAGER = Path(__file__).resolve().parents[2] / "contrib" / "mixdesk" / "pager.py"


def test_the_start_code_loads_the_pager_by_path_and_hands_the_old_desk_over():
    code = desk_pager.start_code(PAGER, {"pages": []}, 8986)
    assert str(PAGER) in code and "CARRY" in code and "m.start(song" in code and "8986" in code


def test_a_call_with_no_pager_answers_none():
    with FakeLive(hw002_like()) as live:
        assert desk_pager.call(live, "m.DESK.page") is None


def test_the_open_sets_name_is_its_files_stem_or_nothing():
    with FakeLive(hw002_like()) as live:
        assert openset.open_set_name(live) == ""  # the fake set has no file: an unsaved set
        live.song.file_path = "/Sets/HW002_121_pp_finish Project/HW002_121_pp_finish.als"
        assert openset.open_set_name(live) == "HW002_121_pp_finish"
