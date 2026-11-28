"""Songs (zpkt.app.songs): names, the index, which songs carry the desk's own pages, and the desk moved onto a song."""

from __future__ import annotations

from pathlib import Path

import pytest

from zpkt.app import songs
from zpkt.app.bus import BadRequest
from zpkt.app.desk import Settings


def test_file_name_is_prefixed_letters_and_digits() -> None:
    assert songs.file_name("Night Drive (v2)") == "song_night_drive_v2"
    assert songs.file_name("  Ölmond 124  ") == "song_lmond_124"
    with pytest.raises(BadRequest):
        songs.file_name("!!!")


def test_clean_title_refuses_empty_and_long() -> None:
    assert songs.clean_title("  Night   Drive ") == "Night Drive"
    with pytest.raises(BadRequest):
        songs.clean_title("   ")
    with pytest.raises(BadRequest):
        songs.clean_title("x" * (songs.MAX_TITLE + 1))


def test_remember_adds_once_and_moves_current(tmp_path: Path) -> None:
    index = tmp_path / "songs.json"
    songs.remember("song_a", "A", desk=False, path=index)
    songs.remember("song_b", "B", desk=False, path=index)
    songs.remember("song_a", path=index)
    data = songs.read_index(index)
    assert [s["name"] for s in data["songs"]] == ["song_a", "song_b"]
    assert data["current"] == "song_a"
    assert songs.entry(data, "song_a") == {"name": "song_a", "title": "A", "desk": False}


def test_desk_song_is_the_home_set_or_one_marked(tmp_path: Path) -> None:
    index = tmp_path / "songs.json"
    songs.remember("HW002_copy", "copy", desk=True, path=index)
    songs.remember("song_new", "new", desk=False, path=index)
    assert songs.is_desk_song("HW002_home", "HW002_home", path=index)
    assert songs.is_desk_song("HW002_copy", "HW002_home", path=index)
    assert not songs.is_desk_song("song_new", "HW002_home", path=index)
    assert not songs.is_desk_song("song_unknown", "HW002_home", path=index)


def test_settings_for_song_moves_every_per_set_folder(tmp_path: Path) -> None:
    s = Settings(
        set_name="HW002_home",
        viz_dir=tmp_path,
        http_port=1,
        udp_port=2,
        meter_port=3,
        live_port=None,
        history_dir=tmp_path / "h",
        checkpoints_dir=tmp_path / "c" / "HW002_home",
        surfaces_dir=tmp_path / "s" / "HW002_home",
        pages_dir=tmp_path / "p" / "HW002_home",
    )
    t = s.for_song("song_night")
    assert t.set_name == "song_night"
    assert t.home_set == "HW002_home"
    assert t.checkpoints_dir.name == "song_night"
    assert t.surfaces_dir.name == "song_night"
    assert t.pages_dir is not None and t.pages_dir.name == "song_night"
    assert t.changes_file is None  # a desk that writes no change stream does not start one
    assert t.for_song("song_other").home_set == "HW002_home"
