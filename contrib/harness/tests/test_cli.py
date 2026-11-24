"""The harness command line for what stays: serve, gemini, artist show, lab-params, lab-audio, lab-bars. Each command
is dispatched with its arguments; the work itself is replaced (no server, no Gemini CLI, no Live set)."""

from __future__ import annotations

import sys

import pytest

from harness import cli
from harness.config import Config


def run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", *args])
    cli.main()


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> Config:
    c = Config(studio_dir=tmp_path / "studio", skrng_dir=tmp_path / "skrng", lab_audio=tmp_path / "lab")
    monkeypatch.setattr(cli, "Config", lambda: c)
    return c


def test_gemini_passes_everything_after_it_to_gemini_cli(monkeypatch):
    seen = []

    def fake_exec(args):
        seen.append(args)
        raise SystemExit(0)

    monkeypatch.setattr("harness.gemini.exec_cli", fake_exec)
    with pytest.raises(SystemExit):
        run(monkeypatch, "gemini", "-p", "hello", "--model", "flash")
    assert seen == [["-p", "hello", "--model", "flash"]]


def test_gemini_without_a_key_says_where_to_put_it(monkeypatch):
    monkeypatch.setattr("harness.config.secret", lambda name: None)
    with pytest.raises(SystemExit) as e:
        run(monkeypatch, "gemini", "-p", "hello")
    assert "zpkt-gemini-api-key" in str(e.value)


def test_serve_runs_the_service_with_the_config(monkeypatch, cfg):
    served = []

    async def fake_serve(c):
        served.append(c)

    monkeypatch.setattr("harness.service.serve", fake_serve)
    run(monkeypatch, "serve")
    assert served == [cfg]


def test_artist_show_prints_the_repertoire(monkeypatch, cfg, capsys):
    run(monkeypatch, "artist", "show")
    out = capsys.readouterr().out
    assert out.startswith("repertoire v1 (parent None): ") and "plates: 0" in out
    assert (cfg.studio_dir / "artist" / "artist.sqlite3").is_file()


def test_lab_params_counts_by_stage(monkeypatch, cfg, capsys, tmp_path):
    from harness.studio import lab_params

    seen = []

    def fake_build(als=None):
        seen.append(als)
        return [{"stage": "bass"}, {"stage": "bass"}, {"stage": "drums"}]

    monkeypatch.setattr(lab_params, "build", fake_build)
    run(monkeypatch, "lab-params", "--set", str(tmp_path / "x.als"))
    assert seen == [tmp_path / "x.als"]
    assert capsys.readouterr().out.splitlines()[:3] == ["bass: 2", "drums: 1", f"3 parameters -> {lab_params.OUT}"]


def test_lab_audio_and_bars_read_the_set_they_are_given(monkeypatch, cfg, capsys, tmp_path):
    from harness.studio import lab_audio, lab_bars

    calls = []
    monkeypatch.setattr(lab_audio, "build", lambda out, **kw: calls.append(("audio", out, kw)) or {})
    monkeypatch.setattr(lab_audio, "summary", lambda m: "audio summary")
    monkeypatch.setattr(lab_bars, "build", lambda **kw: calls.append(("bars", kw)) or {})
    monkeypatch.setattr(lab_bars, "summary", lambda d: "bars summary")
    run(monkeypatch, "lab-audio", "--set", str(tmp_path / "x.als"))
    run(monkeypatch, "lab-audio", "--out", str(tmp_path / "elsewhere"))
    run(monkeypatch, "lab-bars")
    assert calls == [("audio", cfg.lab_audio, {"als": tmp_path / "x.als"}), ("audio", tmp_path / "elsewhere", {}),
                     ("bars", {})]
    assert capsys.readouterr().out.splitlines() == ["audio summary", "audio summary", "bars summary",
                                                    f"-> {lab_bars.OUT}"]


def test_no_command_is_a_usage_error(monkeypatch):
    with pytest.raises(SystemExit) as e:
        run(monkeypatch)
    assert e.value.code == 2
