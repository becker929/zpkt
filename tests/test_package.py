"""One package, four commands, three old names: what other repos, skills and habits rely on after the rename."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(sys.executable).parent


@pytest.mark.parametrize(
    ("script", "says"),
    [
        ("zpkt", "zpkt COMMAND"),
        ("hands", "DAW control layer for Ableton Live."),
        ("ears", "Measure a render."),
        ("mlab", "usage: mlab"),
    ],
)
def test_each_console_script_is_installed_and_prints_help(script: str, says: str) -> None:
    res = subprocess.run([str(BIN / script), "--help"], capture_output=True, text=True, env={"COLUMNS": "200"})
    assert res.returncode == 0, res.stderr
    assert says in res.stdout


def _words(text: str) -> list[str]:
    """Help text without its box drawing and padding (rich pads the box to the usage line's length)."""
    return [w for w in text.split() if w.strip("─│╭╮╰╯")]


@pytest.mark.parametrize(("part", "old"), [("live", "hands"), ("audio", "ears")])
def test_zpkt_part_is_the_old_command(part: str, old: str) -> None:
    new = subprocess.run([str(BIN / "zpkt"), part, "--help"], capture_output=True, text=True, env={"COLUMNS": "200"})
    was = subprocess.run([str(BIN / old), "--help"], capture_output=True, text=True, env={"COLUMNS": "200"})
    assert new.returncode == was.returncode == 0, new.stderr
    assert _words(new.stdout.replace(f"zpkt {part}", old)) == _words(was.stdout)


def test_zpkt_refuses_an_unknown_part() -> None:
    res = subprocess.run([str(BIN / "zpkt"), "eyes"], capture_output=True, text=True)
    assert res.returncode == 2 and "live" in res.stdout and "audio" in res.stdout


def test_old_and_new_names_are_the_same_modules() -> None:
    import ears.meters.loudness
    import hands.cli
    import hands.live.cli
    import hands.live.state
    import hands.testing.fakelive
    import mlab.loudness

    import zpkt.audio.meters.loudness
    import zpkt.live.cli
    import zpkt.live.live_cli
    import zpkt.live.state
    import zpkt.live.testing.fakelive
    import zpkt.live.transport
    from hands.live import transport

    assert hands.live.state is zpkt.live.state
    assert hands.live.cli is zpkt.live.live_cli  # the one flattened name that collided
    assert hands.cli is zpkt.live.cli
    assert transport is zpkt.live.transport
    assert hands.testing.fakelive is zpkt.live.testing.fakelive
    assert ears.meters.loudness is zpkt.audio.meters.loudness is mlab.loudness
    assert zpkt.live.state.__spec__.name == "zpkt.live.state"  # a module keeps its own spec
    assert zpkt.live.cli is importlib.import_module("zpkt.live").cli  # an alias does not rebind zpkt.live's names


def test_patching_the_old_name_patches_the_module(monkeypatch: pytest.MonkeyPatch) -> None:
    import hands.config

    from zpkt.live import config

    monkeypatch.setattr(hands.config, "rig", "patched")
    assert config.rig == "patched"


def test_old_package_names_keep_their_exports() -> None:
    import ears
    import hands
    import mlab
    import zpkt.audio

    assert ears.analyze is zpkt.audio.analyze and ears.AudioProfile is zpkt.audio.AudioProfile
    assert hands.__version__ == mlab.__version__ == "0.1.0"


def test_live_imports_nothing_from_audio() -> None:
    """zpkt[live] installs without the audio extra, so the live CLI must not import its libraries."""
    code = (
        "import sys, zpkt.live.cli, zpkt.live.testing.fakelive, hands.live.state;"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('scipy', 'librosa', 'pyloudnorm', 'onnxruntime')"
        " or m.startswith('zpkt.audio'));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_python_m_runs_the_old_meters_command() -> None:
    for module in ("mlab", "ears.meters", "zpkt.audio.meters"):
        res = subprocess.run([sys.executable, "-m", module, "--help"], capture_output=True, text=True)
        assert res.returncode == 0 and "usage:" in res.stdout, (module, res.stderr)


def test_zpkt_app_starts_the_app() -> None:
    """`zpkt app` was reserved ("not built yet") until the desk's server moved in (24 Nov 2026)."""
    import zpkt.app

    res = subprocess.run([str(BIN / "zpkt"), "app", "--help"], capture_output=True, text=True)
    assert res.returncode == 0 and "--adapters" in res.stdout and "--port" in res.stdout
    usage = subprocess.run([str(BIN / "zpkt")], capture_output=True, text=True).stdout
    assert "app" in usage and "reserved" not in usage and "not built" not in usage
    assert zpkt.app.__doc__ and "only door to Live" in zpkt.app.__doc__


def test_zpkt_live_reaches_the_live_group_without_saying_live_twice() -> None:
    from zpkt.cli import live_args

    commands, live_commands = ["live", "rig", "record"], ["ping", "exec", "state"]
    assert live_args(["ping"], commands, live_commands) == ["live", "ping"]
    assert live_args(["exec", "--json", "result = 1"], commands, live_commands) == [
        "live",
        "exec",
        "--json",
        "result = 1",
    ]
    assert live_args(["live", "ping"], commands, live_commands) == ["live", "ping"]
    assert live_args(["rig", "check"], commands, live_commands) == ["rig", "check"]
    assert live_args(["--help"], commands, live_commands) == ["--help"]
    assert live_args([], commands, live_commands) == []
    assert live_args(["record"], commands, [*live_commands, "record"]) == ["record"]  # hands' own command wins


def test_zpkt_live_ping_help_is_hands_live_ping_help() -> None:
    env = {"COLUMNS": "200"}
    short = subprocess.run([str(BIN / "zpkt"), "live", "ping", "--help"], capture_output=True, text=True, env=env)
    long = subprocess.run(
        [str(BIN / "zpkt"), "live", "live", "ping", "--help"], capture_output=True, text=True, env=env
    )
    assert short.returncode == 0, short.stderr
    assert "Usage: zpkt live ping" in short.stdout and "zpkt live live" not in short.stdout
    assert short.stdout == long.stdout.replace("zpkt live live ping", "zpkt live ping")


def test_no_live_command_shares_a_name_with_a_hands_command() -> None:
    import typer

    from zpkt.live.cli import app

    hands = typer.main.get_group(app)
    assert not set(hands.commands) & set(hands.commands["live"].commands)  # type: ignore[attr-defined]
