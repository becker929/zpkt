"""The supervisor loads the pager again when Live raises from it (a set was opened under it), 25 Nov 2026."""

from __future__ import annotations

from types import SimpleNamespace

from zpkt.app import desk as D
from zpkt.live.transport import LiveError, McpResult

STALE = "Python argument types in None.None(DeviceParameter) did not match C++ signature"


def a_desk(check):
    """A Desk with only what one supervisor step touches: the pager check, a reload and the state."""
    d = D.Desk.__new__(D.Desk)
    d._ensured = d._started = True
    d._stale_reload_at = 0.0
    d.history = SimpleNamespace(cur=None)
    d.states, d.reloads = [], []
    d.check_pager = check
    d.restart_pager = lambda: d.reloads.append(1)
    d.set_state = lambda snap, live: d.states.append(live)
    return d


def raises(exc):
    def check():
        raise exc

    return check


def test_a_pager_live_raises_from_is_loaded_again():
    d = a_desk(raises(LiveError(STALE, McpResult("error", error=STALE))))
    d.supervise_once(now=lambda: 100.0)
    assert d.reloads == [1] and d.states == []


def test_it_is_loaded_again_at_most_once_every_thirty_seconds():
    d = a_desk(raises(LiveError(STALE, McpResult("error", error=STALE))))
    d.supervise_once(now=lambda: 100.0)
    d.supervise_once(now=lambda: 110.0)  # still failing: report, do not reload again yet
    assert d.reloads == [1] and d.states[-1].startswith("Live does not answer")
    d.supervise_once(now=lambda: 100.0 + D.STALE_RETRY_S)
    assert d.reloads == [1, 1]


def test_live_out_of_reach_is_reported_and_nothing_is_reloaded():
    d = a_desk(raises(LiveError("Cannot reach Ableton")))  # no reply from Live: no result
    d.supervise_once(now=lambda: 100.0)
    assert d.reloads == [] and d.states == ["Live does not answer (Cannot reach Ableton)"]
    d = a_desk(raises(OSError("refused")))
    d.supervise_once(now=lambda: 100.0)
    assert d.reloads == [] and d.states == ["Live does not answer (refused)"]


def test_a_reload_that_fails_is_reported():
    d = a_desk(raises(LiveError(STALE, McpResult("error", error=STALE))))

    def reload_fails():
        raise LiveError("Cannot reach Ableton")

    d.restart_pager = reload_fails
    d.supervise_once(now=lambda: 100.0)
    assert d.states == ["Live does not answer (Cannot reach Ableton)"]
