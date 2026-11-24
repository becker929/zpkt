"""One project, two old names: `ears` offers every meter command, and `mlab` still imports and runs as before."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

from zpkt.audio.cli import app
from zpkt.audio.meters import cli as meters_cli
from signals import SR, mix, write
from typer.testing import CliRunner

BIN = Path(sys.executable).parent


def test_mlab_names_are_the_meters_modules() -> None:
    import zpkt.audio.meters.loudness
    import mlab
    import mlab.loudness
    from mlab import target
    from mlab.util import db

    assert mlab.loudness is zpkt.audio.meters.loudness and target is importlib.import_module("zpkt.audio.meters.target")
    assert db is importlib.import_module("zpkt.audio.meters.util").db
    assert mlab.loudness.__spec__.name == "zpkt.audio.meters.loudness"  # the module keeps its own spec
    assert mlab.__version__ == "0.1.0"


def test_ears_runs_every_meter_command(tmp_path, capsys) -> None:
    runner = CliRunner()
    listed = runner.invoke(app, ["--help"], env={"COLUMNS": "200"}).output
    for name in meters_cli.commands():
        assert f" {name} " in listed, name
    path = write(tmp_path / "x.wav", mix(3.0), SR, "PCM_16")
    via_ears = runner.invoke(app, ["bitdepth", str(path)])
    assert via_ears.exit_code == 0, via_ears.output
    meters_cli.main(["bitdepth", str(path)])
    assert json.loads(via_ears.output) == json.loads(capsys.readouterr().out)
    usage = runner.invoke(app, ["target", str(path)])
    assert usage.exit_code == 2 and "ears target: error: the following arguments are required: --refs" in usage.output


def test_both_entry_points_are_installed(tmp_path) -> None:
    path = write(tmp_path / "x.wav", mix(3.0), SR, "PCM_16")
    for script in ("ears", "mlab"):
        res = subprocess.run([str(BIN / script), "bitdepth", str(path)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout)["effective_bits"] == 16
