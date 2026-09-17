from __future__ import annotations

from pathlib import Path

import pytest

from audio_browser.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ConfigError,
    load_config,
    parse_config,
)


def test_relative_paths_resolve_against_the_config_file(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    config = parse_config(
        {"db": "index.db", "roots": [{"name": "lib", "path": "lib"}]},
        base_dir=tmp_path,
    )
    assert config.db_path == tmp_path / "index.db"
    assert config.roots[0].path == (tmp_path / "lib").resolve()


def test_symlinked_root_is_stored_resolved(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    config = parse_config(
        {"roots": [{"name": "link", "path": "link"}]}, base_dir=tmp_path
    )
    assert config.roots[0].path == real.resolve()


def test_duplicate_root_names_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {
                "roots": [
                    {"name": "a", "path": "x"},
                    {"name": "a", "path": "y"},
                ]
            },
            base_dir=tmp_path,
        )


def test_no_roots_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        parse_config({"roots": []}, base_dir=tmp_path)


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_load_config_reads_toml(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    path = tmp_path / "config.toml"
    path.write_text(
        'db = "out.db"\n\n[[roots]]\nname = "lib"\npath = "lib"\n', encoding="utf-8"
    )
    config = load_config(path)
    assert config.db_path == tmp_path / "out.db"
    assert config.root("lib") is not None
    assert config.root("missing") is None


def test_server_defaults_bind_broadly(tmp_path: Path) -> None:
    config = parse_config({"roots": [{"name": "a", "path": "."}]}, base_dir=tmp_path)
    assert config.server.host == DEFAULT_HOST == "0.0.0.0"
    assert config.server.port == DEFAULT_PORT == 8090
    assert "http://localhost:3100" in config.server.cors_origins


def test_server_section_overrides_defaults(tmp_path: Path) -> None:
    config = parse_config(
        {
            "roots": [{"name": "a", "path": "."}],
            "server": {
                "host": "127.0.0.1",
                "port": 9999,
                "cors_origins": ["http://example.test"],
                "cors_origin_regex": "",
            },
        },
        base_dir=tmp_path,
    )
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 9999
    assert config.server.cors_origins == ("http://example.test",)
    assert config.server.cors_origin_regex == ""


def test_frontend_port_moves_the_default_cors_origins(tmp_path: Path) -> None:
    config = parse_config(
        {
            "roots": [{"name": "a", "path": "."}],
            "server": {"frontend_port": 4000},
        },
        base_dir=tmp_path,
    )
    assert config.server.cors_origins == (
        "http://localhost:4000",
        "http://127.0.0.1:4000",
    )
    assert config.server.cors_origin_regex.endswith(":4000")


@pytest.mark.parametrize(
    "server",
    [
        {"port": "8090"},
        {"port": 0},
        {"port": 70000},
        {"host": ""},
        {"cors_origins": "http://x"},
        {"cors_origin_regex": 7},
    ],
)
def test_bad_server_settings_are_rejected(tmp_path: Path, server: dict) -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {"roots": [{"name": "a", "path": "."}], "server": server},
            base_dir=tmp_path,
        )


# ----------------------------------------------------------------- projects


def test_projects_defaults_to_three_slots_beside_the_config() -> None:
    config = parse_config({"roots": [{"name": "a", "path": "a"}]}, Path("/base"))
    assert config.projects is not None
    assert config.projects.dir == Path("/base/projects")
    assert [config.projects.cap(c) for c in ("stored", "collage", "enrich")] == [3, 3, 3]


def test_turning_the_board_down_is_one_line() -> None:
    config = parse_config(
        {"roots": [{"name": "a", "path": "a"}], "projects": {"cap": 1}},
        Path("/base"),
    )
    assert config.projects is not None
    assert [config.projects.cap(c) for c in ("stored", "collage", "enrich")] == [1, 1, 1]


def test_one_column_can_be_capped_on_its_own() -> None:
    config = parse_config(
        {
            "roots": [{"name": "a", "path": "a"}],
            "projects": {"cap": 3, "caps": {"enrich": 1}},
        },
        Path("/base"),
    )
    assert config.projects is not None
    assert [config.projects.cap(c) for c in ("stored", "collage", "enrich")] == [3, 3, 1]


def test_a_cap_of_zero_is_a_setting_and_closes_the_column() -> None:
    config = parse_config(
        {"roots": [{"name": "a", "path": "a"}], "projects": {"cap": 0}},
        Path("/base"),
    )
    assert config.projects is not None
    assert config.projects.cap("stored") == 0


def test_a_cap_that_is_not_a_whole_number_is_refused_not_rounded() -> None:
    """Somebody editing this is nearly always turning the cap down.

    A typo in that edit must not quietly hand back a looser board than the one
    they asked for, so it stops rather than guessing.
    """
    for bad in (1.5, -1, "two", True):
        with pytest.raises(ConfigError):
            parse_config(
                {"roots": [{"name": "a", "path": "a"}], "projects": {"cap": bad}},
                Path("/base"),
            )


def test_a_cap_naming_something_that_is_not_a_column_is_refused() -> None:
    with pytest.raises(ConfigError):
        parse_config(
            {
                "roots": [{"name": "a", "path": "a"}],
                "projects": {"caps": {"mastering": 2}},
            },
            Path("/base"),
        )
