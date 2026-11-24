"""Storage sweeping: what goes, what stays, and the refusal to record on a full disk."""

import gzip
import json
import os
import time

import pytest

from hands.live import sweep
from hands.live.panel import PanelError

HOUR, DAY = 3600.0, 86400.0


def put(path, size=1000, age=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


def names(result):
    return sorted(os.path.basename(i["path"]) for i in result["items"])


def project(tmp_path):
    rec = tmp_path / "proj" / "Samples" / "Recorded"
    used, loose, fresh = (
        "Render 0001 [2026-10-01 100000].wav",
        "Render 0001 [2026-10-02 100000].wav",
        "Render 0001 [2026-11-18 100000].wav",
    )
    put(rec / used, age=2 * DAY)
    put(rec / loose, age=2 * DAY)
    put(rec / (loose + ".asd"), 10, age=2 * DAY)
    put(rec / fresh, age=60)  # a render under way
    put(rec / "Main 0001 [2026-10-02 100000].wav", age=9 * DAY)  # the user's own recording
    put(rec / "vocal take.wav", age=9 * DAY)
    (tmp_path / "proj" / "Backup").mkdir()
    with gzip.open(tmp_path / "proj" / "Backup" / "old.als", "wb") as f:
        f.write(f'<SampleRef><Path Value="Samples/Recorded/{used}" /></SampleRef>'.encode())
    return tmp_path / "proj", used, loose, fresh


def test_takes_no_set_uses_go_and_everything_else_stays(tmp_path):
    proj, used, loose, fresh = project(tmp_path)
    out = tmp_path / "renders"
    out.mkdir(exist_ok=True)
    r = sweep.sweep(out, [proj])
    assert names(r) == [loose, loose + ".asd"]
    assert not r["applied"] and (proj / "Samples" / "Recorded" / loose).exists()
    r = sweep.sweep(out, [proj], apply=True)
    assert r["files"] == 2 and r["kinds"]["take"]["files"] == 2
    left = sorted(p.name for p in (proj / "Samples" / "Recorded").iterdir())
    assert left == sorted(["Main 0001 [2026-10-02 100000].wav", fresh, used, "vocal take.wav"])
    assert "nothing to sweep" in sweep.report(sweep.sweep(out, [proj]))


def test_a_take_the_open_set_plays_stays(tmp_path):
    proj, used, loose, fresh = project(tmp_path)
    out = tmp_path / "renders"
    out.mkdir(exist_ok=True)
    r = sweep.sweep(out, [proj], in_use={str((proj / "Samples" / "Recorded" / loose).resolve())})
    assert names(r) == []


def test_the_take_folder_is_remembered_from_renders(tmp_path):
    proj, used, loose, fresh = project(tmp_path)
    out = tmp_path / "renders"
    out.mkdir(exist_ok=True)
    sweep.note_takes(out, proj / "Samples" / "Recorded")
    assert names(sweep.sweep(out)) == [loose, loose + ".asd"]


def panel_files(out, age):
    for n in [
        "bass.wav",
        "bass-2.wav",
        "bass-3.wav",
        "bass-4.wav",
        "bass-g1-a.wav",
        "bass-g1-b.wav",
        "bass-g1-b-m.wav",
        "bass-g2-a.wav",
        "bass-g2-b.wav",
        "gone-g1-a.wav",
        "glass-hour-2.wav",
        "my-song-g1-final.wav",
        "film.mp4",
    ]:
        put(out / n, age=age)
    put(out / ".bass.take.wav", age=age)
    grid = lambda i: {
        "id": i,
        "options": [
            {"letter": "A", "file": f"renders/bass-g{i}-a.wav"},
            {"letter": "B", "file": f"renders/bass-g{i}-b.wav", "matched": f"renders/bass-g{i}-b-m.wav"},
        ],
    }
    (out / "bass.panel.json").write_text(
        json.dumps(
            {
                "name": "bass",
                "renders": [f"renders/{n}" for n in ["bass.wav", "bass-2.wav", "bass-3.wav", "bass-4.wav"]],
                "grids": [grid(1), grid(2)],
            }
        )
    )


def test_old_versions_and_old_grids_go_after_a_week(tmp_path):
    out = tmp_path / "renders"
    panel_files(out, age=8 * DAY)
    r = sweep.sweep(out, apply=True)
    assert names(r) == sorted(
        [
            ".bass.take.wav",
            "bass.wav",
            "bass-2.wav",
            "bass-g1-a.wav",
            "bass-g1-b.wav",
            "bass-g1-b-m.wav",
            "gone-g1-a.wav",
        ]
    )
    kept = {p.name for p in out.iterdir()}
    assert {
        "bass-3.wav",
        "bass-4.wav",
        "bass-g2-a.wav",
        "bass-g2-b.wav",
        "glass-hour-2.wav",
        "my-song-g1-final.wav",
        "film.mp4",
    } <= kept
    made = json.loads((out / "bass.panel.json").read_text())
    assert made["grids"][0].get("swept") is True and not made["grids"][1].get("swept")


def test_young_renders_wait_unless_the_disk_is_short(tmp_path):
    out = tmp_path / "renders"
    panel_files(out, age=2 * HOUR)
    assert names(sweep.sweep(out)) == [".bass.take.wav"]
    assert len(sweep.sweep(out, pressure=True)["items"]) == 7
    panel_files(out, age=60)
    assert names(sweep.sweep(out, pressure=True)) == []  # under an hour old: never


def test_a_render_is_refused_when_there_is_no_room(tmp_path):
    out = tmp_path / "renders"
    out.mkdir(exist_ok=True)
    sweep.make_room(out, 30, free=lambda p: 50 * 2**30)
    with pytest.raises(PanelError, match="only 113 MB is free"):
        sweep.make_room(out, 130, free=lambda p: 113 * 2**20)
    sweep.make_room(out, 10, free=lambda p: 400 * 2**20)  # low, but room for a short take


def test_a_swept_grid_cannot_be_picked(tmp_path):
    from hands.live import versions

    out = tmp_path / "renders"
    panel_files(out, age=8 * DAY)
    sweep.sweep(out, apply=True)
    with pytest.raises(PanelError, match="was swept"):
        versions.pick(None, "bass", out, 1, "A")
