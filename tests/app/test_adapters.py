"""Adapters: the protocol, the registry that finds them, and how a new one is added without editing the core."""

from __future__ import annotations

import sys
import textwrap

import pytest

from zpkt.app import adapters
from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.bus import Command


def test_the_web_and_agents_adapters_are_discovered_by_name():
    assert {"web", "agents"} <= set(adapters.discover())
    assert adapters.discover()["web"].name == "web" and adapters.discover()["agents"].name == "agents"


def test_an_unknown_adapter_is_an_error_that_lists_the_known_ones(rig):
    context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
    with pytest.raises(ValueError, match="no adapter nonesuch; the adapters are agents, api, listen, midi, web"):
        adapters.create(["nonesuch"], context)


def test_the_web_adapter_starts_serves_and_stops(tmp_path):
    from tests.app.conftest import FakeMeter, make_settings
    from zpkt.app.connections import LiveConnections
    from zpkt.app.desk import Desk
    from zpkt.live.testing import FakeLive, hw002_like

    desk = Desk(make_settings(tmp_path), connections=LiveConnections(FakeLive(hw002_like()), FakeMeter()))
    context = AppContext(desk.bus, desk, desk.settings)
    (web,) = adapters.create(["web"], context)
    web.supervise = False
    web.start()
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{web.port}/app/", timeout=10) as r:
            assert r.status == 200
    finally:
        web.stop()


def test_a_new_adapter_is_one_module_that_defines_ADAPTER_and_the_core_is_not_edited(rig, tmp_path, monkeypatch):
    """The MiniLab, the API and the agents will be added like this one: a module in zpkt/app/adapters/."""
    package = tmp_path / "extra_adapters"
    package.mkdir()
    (package / "__init__.py").write_text(
        textwrap.dedent(
            """
            from zpkt.app.adapters import AdapterSpec, discover as _discover  # noqa: F401
            """
        )
    )
    (package / "knobby.py").write_text(
        textwrap.dedent(
            """
            from zpkt.app.adapters import AdapterSpec
            from zpkt.app.bus import Command

            class Knobby:
                name = "knobby"
                def __init__(self, context): self.context, self.started = context, False
                def start(self): self.started = True
                def stop(self): self.started = False
                def turn(self, key, n):
                    return self.context.bus.submit(Command("mix.set", "minilab", {"norms": [[key, n]]}))

            ADAPTER = AdapterSpec("knobby", Knobby)
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    import extra_adapters.knobby as knobby

    try:
        context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
        adapter = knobby.ADAPTER.make(context)
        adapter.start()
        key = next(v["key"] for k, v in rig.state()["values"].items() if v.get("key") and k.startswith("0:f"))
        assert adapter.turn(key, 0.4)[0] == 200  # a hand that is not the web: the bus stamps who
        assert rig.desk.history.entries[0]["who"] == "minilab"
        assert isinstance(knobby.ADAPTER, AdapterSpec)
    finally:
        sys.modules.pop("extra_adapters", None)
        sys.modules.pop("extra_adapters.knobby", None)
    assert Command  # imported for the module above
