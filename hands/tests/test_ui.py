"""hands.live.ui without running osascript: subprocess is replaced by a script of answers."""
from __future__ import annotations

import subprocess

import pytest

from hands.live import ui


class FakeOsascript:
    """Stands in for subprocess.run: answers each call from a list of (returncode, stdout, stderr)."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        code, out, err = self.answers.pop(0)
        return subprocess.CompletedProcess(argv, code, out, err)


@pytest.fixture
def fake(monkeypatch):
    def install(*answers, hs=True):
        f = FakeOsascript(answers)
        monkeypatch.setattr(ui.subprocess, "run", f)
        monkeypatch.setattr(ui.shutil, "which", lambda name: "/usr/local/bin/hs" if hs else None)
        monkeypatch.setattr(ui, "_direct_works", False)
        monkeypatch.setattr(ui.time, "sleep", lambda s: None)
        return f
    return install


def test_osa_returns_stripped_output(fake):
    f = fake((0, "HW002_121_pp_kit_c8x4\n", ""))
    assert ui.front_title() == "HW002_121_pp_kit_c8x4"
    assert f.calls[0][:2] == ["osascript", "-e"] and 'front window of process "Live"' in f.calls[0][2]


def test_no_accessibility_reruns_through_hammerspoon(fake):
    f = fake((1, "", "execution error: osascript is not allowed assistive access. (-1719)"),
             (0, "-- Loading extension: osascript\ntrue\n", ""))
    assert ui.menu_enabled("File", "Save Live Set") is True
    assert f.calls[1][:2] == ["hs", "-c"]


def test_hammerspoon_failure_is_an_error(fake):
    fake((1, "", "System Events got an error: Can't get window 1 (-1728)"),
         (0, "System Events got an error (-1728)\n__OSA_FAIL__\n", ""))
    with pytest.raises(ui.UiError, match="-1728"):
        ui.front_title()


def test_once_direct_calls_work_a_1728_is_a_real_error(fake):
    f = fake((0, "x", ""), (1, "", "Can't get window 1 of process \"Live\". (-1728)"))
    ui.front_title()
    with pytest.raises(ui.UiError, match="-1728"):
        ui.front_title()
    assert len(f.calls) == 2           # no detour through Hammerspoon


def test_without_hammerspoon_the_error_stands(fake):
    fake((1, "", "not allowed assistive access"), hs=False)
    with pytest.raises(ui.UiError, match="assistive"):
        ui.dialogs()


def test_windows_and_dialogs(fake):
    listing = "HW002_121_pp_kit_c8x4|AXStandardWindow\nExport Audio/Video|AXDialog\nSave|AXDialog\n"
    fake((0, listing, ""), (0, listing, ""))
    assert ui.windows()[1] == ("Export Audio/Video", "AXDialog")
    assert ui.dialogs() == 2


def test_menu_waits_until_the_item_is_enabled(fake):
    f = fake((0, "false", ""), (0, "false", ""), (0, "true", ""), (0, "", ""))
    assert ui.menu("Edit", "Delete Time", tries=3) is True
    assert "click menu item \"Delete Time\" of menu \"Edit\"" in f.calls[-1][2]
    fake((0, "false", ""), (0, "false", ""))
    assert ui.menu("Edit", "Delete Time", tries=2) is False


def test_menu_names_are_quoted(fake):
    f = fake((0, "true", ""))
    ui.menu_enabled("Edit", 'Say "hi"')
    assert 'menu item "Say \\"hi\\""' in f.calls[0][2]


def test_reap_modals_runs_the_packaged_script(fake):
    f = fake((0, "CLEAN\n", ""))
    assert ui.reap_modals() == "CLEAN"
    assert f.calls[0][1] == str(ui.REAP_SCRIPT) and f.calls[0][2] == "check"
    assert ui.REAP_SCRIPT.exists()
