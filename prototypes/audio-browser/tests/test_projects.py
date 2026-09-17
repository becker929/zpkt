"""Projects, the board, and the two races the mock backend could not reach.

Every test here runs against a real directory of real JSON files. There is no
in-memory project store to agree with a real one.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from audio_browser.projects import model
from audio_browser.projects.store import Caps, ProjectStore

from conftest import Fixture, schemas_dir, tree_snapshot


@pytest.fixture
def validator() -> Any:
    return model.load_validator(schemas_dir())


def read_file(fixture: Fixture, project_id: str) -> dict[str, Any]:
    """The document straight off disk, around the API and around the index."""
    path = fixture.projects_dir / f"{project_id}.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def write_file(fixture: Fixture, project_id: str, document: object) -> Path:
    path = fixture.projects_dir / f"{project_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def commit_all(fixture: Fixture, project_id: str, upto: str) -> None:
    """Walk a project down the board, naming each stage it freezes."""
    for column in model.COLUMNS:
        response = fixture.client.post(
            f"/api/projects/{project_id}/commit",
            json={"expect_column": column, "override": True},
        )
        assert response.status_code == 200, response.text
        if column == upto:
            return


# ------------------------------------------------------------ the pure model


def test_the_stored_manifest_is_sorted_deduplicated_and_newline_joined() -> None:
    """Both languages must agree on these bytes or the freeze is not checkable."""
    assert model.manifest_input(["b" * 64, "a" * 64, "b" * 64]) == f"{'a' * 64}\n{'b' * 64}"
    assert model.manifest_input([]) == ""


def test_the_stored_digest_survives_reordering_but_not_a_change() -> None:
    one = model.commit_artifact("p", ["b" * 64, "a" * 64], "stored")
    two = model.commit_artifact("p", ["a" * 64, "b" * 64], "stored")
    three = model.commit_artifact("p", ["a" * 64], "stored")
    assert one.digest == two.digest
    assert one.digest != three.digest
    assert one.real is True


def test_the_later_stages_say_their_artifact_is_not_real_yet() -> None:
    """collage and enrich have no view, so their digest is a placeholder."""
    for column in ("collage", "enrich"):
        artifact = model.commit_artifact("p", ["a" * 64], column)  # type: ignore[arg-type]
        assert artifact.real is False
        assert artifact.digest != model.commit_artifact("q", ["a" * 64], column).digest  # type: ignore[arg-type]


def test_a_slug_reads_a_name_that_is_not_latin() -> None:
    assert model.slugify("rust and rebar") == "rust-and-rebar"
    assert model.slugify("  Rust  &&  Rebar  ") == "rust-rebar"
    assert model.slugify("техно 909") == "tekhno-909"
    assert model.slugify("🔥🔥🔥") == "u1f525"
    assert model.slugify("") == "project"


def test_an_id_is_the_day_then_the_name_and_never_collides() -> None:
    made = model.project_id("rust and rebar", "2026-09-16T21:04:00Z")
    assert made == "2026-09-16-rust-and-rebar"
    assert model.unique_project_id(made, [made]) == f"{made}-2"
    assert model.unique_project_id(made, [made, f"{made}-2"]) == f"{made}-3"


def test_the_instant_format_is_the_one_the_schema_accepts(validator: Any) -> None:
    """db.now_iso writes +00:00, which the schema refuses. utc_now writes Z."""
    now = model.utc_now()
    assert now.endswith("Z")
    assert not model.check_project(
        validator, model.new_document("a-project", "a project", now)
    )


# ------------------------------------------------------ mirrored invariants
#
# jsonschema draft 7 cannot say "unique by one key" and cannot compare two
# fields. If Python accepted a file the board rejects, the one-schema guarantee
# would be a lie, so each rule below is checked after the schema passes.


def test_a_repeated_hash_is_refused_although_the_schema_allows_it(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    entry = {"hash": "a" * 64, "added_at": "2026-09-16T21:04:00Z", "role": None, "note": ""}
    document["sounds"] = [entry, dict(entry)]

    assert validator.is_valid(document), "the schema alone lets this through"
    issues = model.check_project(validator, document)
    assert [i.path for i in issues] == ["sounds"]
    assert "set" in issues[0].message


def test_updated_before_created_is_refused(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["updated_at"] = "2026-09-15T21:04:00Z"
    assert validator.is_valid(document)
    assert [i.path for i in model.check_project(validator, document)] == ["updated_at"]


def test_a_commit_dated_before_the_project_is_refused(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["column"] = "collage"
    document["commits"] = [
        {"column": "stored", "at": "2026-01-01T00:00:00Z", "digest": "a" * 64}
    ]
    assert validator.is_valid(document)
    assert [i.path for i in model.check_project(validator, document)] == ["commits.0.at"]


def test_an_abandonment_that_disagrees_with_the_column_is_refused(validator: Any) -> None:
    """Revive and the board would otherwise disagree about the same project."""
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["abandoned"] = {
        "at": "2026-09-17T00:00:00Z", "from": "collage", "reason": ""
    }
    assert validator.is_valid(document)
    assert [i.path for i in model.check_project(validator, document)] == ["abandoned.from"]


def test_the_chain_is_tied_to_the_column_by_the_schema_itself(validator: Any) -> None:
    """A collage project without a stored commit is not a document at all.

    This is what makes "the sound set is frozen from collage onwards" a property
    of the format rather than a rule the app promises to keep.
    """
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["column"] = "collage"
    assert not validator.is_valid(document)
    assert model.check_project(validator, document)


# ------------------------------------------------------------------ the API


def test_the_board_starts_empty_with_the_configured_cap(api: Fixture) -> None:
    board = api.client.get("/api/board").json()
    assert [c["column"] for c in board["columns"]] == ["stored", "collage", "enrich"]
    assert all(c["cap"] == 3 and c["count"] == 0 and not c["over"] for c in board["columns"])
    assert board == {**board, "released": 0, "abandoned": 0, "unreadable": 0}


def test_a_new_project_is_a_file_on_disk(api: Fixture) -> None:
    """The file is the truth, so the first thing to check is that there is one."""
    summary = api.make_project("rust and rebar")
    assert summary["id"] == f"{summary['created_at'][:10]}-rust-and-rebar"
    assert summary["column"] == "stored"
    assert summary["sound_count"] == 0
    # Absent is null, never zero. 0:00 against an empty project is not a length.
    assert summary["duration_s"] is None and summary["sounding_s"] is None

    on_disk = read_file(api, str(summary["id"]))
    assert on_disk["name"] == "rust and rebar"
    assert on_disk["commits"] == [] and on_disk["abandoned"] is None


def test_two_projects_with_one_name_get_two_files(api: Fixture) -> None:
    first = api.project_id("rust and rebar")
    second = api.project_id("rust and rebar")
    assert first != second and second.endswith("-2")
    assert (api.projects_dir / f"{first}.json").is_file()
    assert (api.projects_dir / f"{second}.json").is_file()


def test_a_name_that_is_only_space_is_refused(api: Fixture) -> None:
    assert api.client.post("/api/projects", json={"name": "   "}).status_code == 422


def test_an_id_that_is_not_a_slug_never_reaches_the_filesystem(api: Fixture) -> None:
    for bad in ("../secrets", "..", "Not-A-Slug", "a/b"):
        response = api.client.get(f"/api/projects/{bad}")
        assert response.status_code in (400, 404), f"{bad}: {response.status_code}"


# ------------------------------------------------------------------- the cap


def test_the_cap_refuses_with_the_numbers_the_interface_needs(
    capped_api: Callable[[int], Fixture],
) -> None:
    """Friction, not restriction: it states the cap and offers a way through."""
    api = capped_api(1)
    api.make_project("first")
    refused = api.client.post("/api/projects", json={"name": "second"})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["column"] == "stored" and detail["cap"] == 1 and detail["count"] == 1
    assert detail["overridable"] is True


def test_an_override_gets_through_and_the_column_stays_visibly_over(
    capped_api: Callable[[int], Fixture],
) -> None:
    api = capped_api(1)
    api.make_project("first")
    api.make_project("second", override=True)
    column = api.client.get("/api/board").json()["columns"][0]
    assert column["count"] == 2 and column["cap"] == 1 and column["over"] is True


def test_a_cap_of_zero_closes_the_column(capped_api: Callable[[int], Fixture]) -> None:
    api = capped_api(0)
    assert api.client.post("/api/projects", json={"name": "first"}).status_code == 409
    api.make_project("first", override=True)
    assert api.client.get("/api/board").json()["columns"][0]["over"] is True


def test_two_simultaneous_creates_cannot_both_pass_one_cap_check(
    capped_api: Callable[[int], Fixture],
) -> None:
    """Counting and then writing is a read-then-write, and two interleave.

    Without a lock both requests count zero against a cap of one, both find
    room, and the column ends up holding two with nobody having overridden
    anything. The mock backend was single threaded and could not show this.
    """
    api = capped_api(1)
    start = threading.Barrier(6)
    codes: list[int] = []
    lock = threading.Lock()

    def race(n: int) -> None:
        start.wait()
        response = api.client.post("/api/projects", json={"name": f"racer {n}"})
        with lock:
            codes.append(response.status_code)

    threads = [threading.Thread(target=race, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(codes) == [201, 409, 409, 409, 409, 409]
    assert len(list(api.projects_dir.glob("*.json"))) == 1
    assert api.client.get("/api/board").json()["columns"][0]["count"] == 1


def test_two_creates_of_one_name_never_land_on_one_file(api: Fixture) -> None:
    """O_EXCL is the second guard: the filesystem decides who owns the name."""
    start = threading.Barrier(8)
    ids: list[str] = []
    lock = threading.Lock()

    def race() -> None:
        start.wait()
        response = api.client.post(
            "/api/projects", json={"name": "rust and rebar", "override": True}
        )
        assert response.status_code == 201, response.text
        with lock:
            ids.append(response.json()["id"])

    threads = [threading.Thread(target=race) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(ids)) == 8
    assert len(list(api.projects_dir.glob("*.json"))) == 8


# ---------------------------------------------------------------- membership


def test_a_sound_goes_in_and_comes_out_without_touching_a_file(api: Fixture) -> None:
    before = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    project_id = api.project_id("rust and rebar")
    kick = api.hash_of("kick.wav")

    added = api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    assert added.status_code == 200 and added.json()["member"] is True
    assert added.json()["sound_count"] == 1
    assert [s["hash"] for s in read_file(api, project_id)["sounds"]] == [kick]

    dropped = api.client.delete(f"/api/projects/{project_id}/sounds/{kick}")
    assert dropped.status_code == 200 and dropped.json()["member"] is False
    assert read_file(api, project_id)["sounds"] == []
    assert {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")} == before


def test_adding_the_same_sound_twice_changes_nothing(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    first = read_file(api, project_id)
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    assert read_file(api, project_id) == first


def test_an_unknown_hash_cannot_be_added(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    response = api.client.put(f"/api/projects/{project_id}/sounds/{'b' * 64}")
    assert response.status_code == 404


def test_a_project_reports_the_sounding_length_of_what_it_holds(api: Fixture) -> None:
    """A board card shows playing time, not wall time."""
    loop = api.hash_of("loop.mp3")  # 30 s wall
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO silence (hash, silent_s, duration_s, silent_frac, measured_at)"
        " VALUES (?, 11.0, 30.0, 0.3667, '2026-09-17T00:00:00Z')",
        (loop,),
    )
    conn.executemany(
        "INSERT INTO silence_interval (hash, start_s, end_s) VALUES (?, ?, ?)",
        # The 1 second gap is under the floor and is not taken off.
        [(loop, 0.0, 10.0), (loop, 12.0, 13.0), (loop, 20.0, 30.0)],
    )
    conn.commit()
    conn.close()

    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{loop}")
    summary = api.client.get(f"/api/projects/{project_id}").json()["summary"]
    assert summary["duration_s"] == pytest.approx(30.0)
    assert summary["sounding_s"] == pytest.approx(10.0)


# -------------------------------------------------------------------- commit


def test_committing_out_of_stored_freezes_the_sound_set(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")

    body = api.client.post(
        f"/api/projects/{project_id}/commit", json={"expect_column": "stored"}
    ).json()
    assert body["commit"]["column"] == "stored"
    assert body["commit"]["digest"] == model.digest_of(kick)
    assert body["artifact_real"] is True
    assert body["summary"]["column"] == "collage"
    assert body["summary"]["sound_set_verified"] is True


def test_membership_is_refused_at_the_api_once_stored_is_committed(api: Fixture) -> None:
    """A tab that was open before the commit has to be told no by the server."""
    project_id = api.project_id("rust and rebar")
    kick, hat = api.hash_of("kick.wav"), api.hash_of("hat.wav")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    api.client.post(f"/api/projects/{project_id}/commit", json={"expect_column": "stored"})

    added = api.client.put(f"/api/projects/{project_id}/sounds/{hat}")
    dropped = api.client.delete(f"/api/projects/{project_id}/sounds/{kick}")
    assert added.status_code == 409 and dropped.status_code == 409
    # Not overridable, and not offered as such.
    assert "overridable" not in added.json()["detail"]
    assert [s["hash"] for s in read_file(api, project_id)["sounds"]] == [kick]


def test_an_empty_sound_set_cannot_be_frozen(api: Fixture) -> None:
    """422, and no override. The project could never gain a sound afterwards."""
    project_id = api.project_id("rust and rebar")
    refused = api.client.post(
        f"/api/projects/{project_id}/commit", json={"override": True}
    )
    assert refused.status_code == 422
    assert read_file(api, project_id)["column"] == "stored"


def test_a_stale_expect_column_is_refused_and_no_override_gets_through(
    api: Fixture,
) -> None:
    """The race an adversarial review found, and the reason for expect_column.

    Two tabs both show a project in `stored`. The first presses freeze and the
    project moves to `collage`. The second presses the same button. Without
    `expect_column` that second press freezes the arrangement: a stage nobody
    worked, with a digest of nothing, one way, permanently.
    """
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")

    first = api.client.post(
        f"/api/projects/{project_id}/commit", json={"expect_column": "stored"}
    )
    assert first.status_code == 200

    stale = api.client.post(
        f"/api/projects/{project_id}/commit",
        json={"expect_column": "stored", "override": True},
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert "overridable" not in detail, "a stale client is not a capacity decision"
    assert "stored" in detail["detail"] and "collage" in detail["detail"]

    on_disk = read_file(api, project_id)
    assert on_disk["column"] == "collage"
    assert [c["column"] for c in on_disk["commits"]] == ["stored"]


def test_two_simultaneous_commits_advance_a_project_exactly_one_stage(
    api: Fixture,
) -> None:
    """Commit is one way, so a lost update here is permanent damage."""
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")

    start = threading.Barrier(6)
    codes: list[int] = []
    lock = threading.Lock()

    def race() -> None:
        start.wait()
        response = api.client.post(
            f"/api/projects/{project_id}/commit", json={"expect_column": "stored"}
        )
        with lock:
            codes.append(response.status_code)

    threads = [threading.Thread(target=race) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(codes) == [200, 409, 409, 409, 409, 409]
    on_disk = read_file(api, project_id)
    assert on_disk["column"] == "collage"
    assert [c["column"] for c in on_disk["commits"]] == ["stored"]


def test_a_full_next_column_gates_promotion(
    capped_api: Callable[[int], Fixture],
) -> None:
    """You cannot keep gathering material while the collage bench is full."""
    api = capped_api(1)
    blocker = api.project_id("blocker")
    api.client.put(f"/api/projects/{blocker}/sounds/{api.hash_of('kick.wav')}")
    api.client.post(f"/api/projects/{blocker}/commit", json={"expect_column": "stored"})

    waiting = api.project_id("waiting", override=True)
    api.client.put(f"/api/projects/{waiting}/sounds/{api.hash_of('hat.wav')}")
    refused = api.client.post(
        f"/api/projects/{waiting}/commit", json={"expect_column": "stored"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["column"] == "collage"
    assert refused.json()["detail"]["overridable"] is True

    forced = api.client.post(
        f"/api/projects/{waiting}/commit",
        json={"expect_column": "stored", "override": True},
    )
    assert forced.status_code == 200
    assert api.client.get("/api/board").json()["columns"][1]["over"] is True


def test_committing_out_of_enrich_releases_the_project(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    commit_all(api, project_id, "enrich")

    summary = api.client.get(f"/api/projects/{project_id}").json()["summary"]
    assert summary["column"] == "released"
    assert [c["column"] for c in summary["commits"]] == ["stored", "collage", "enrich"]

    board = api.client.get("/api/board").json()
    assert board["released"] == 1
    assert all(column["count"] == 0 for column in board["columns"])

    again = api.client.post(f"/api/projects/{project_id}/commit", json={})
    assert again.status_code == 409


# ------------------------------------------------------- abandon and revive


def test_abandon_frees_the_slot_and_keeps_the_file(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    left = api.client.post(
        f"/api/projects/{project_id}/abandon", json={"reason": "wrong kick"}
    )
    assert left.status_code == 200
    assert left.json()["abandoned"]["from"] == "stored"
    assert left.json()["abandoned"]["reason"] == "wrong kick"

    assert (api.projects_dir / f"{project_id}.json").is_file()
    board = api.client.get("/api/board").json()
    assert board["columns"][0]["count"] == 0 and board["abandoned"] == 1


def test_abandoning_appends_nothing_to_the_chain(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    commit_all(api, project_id, "stored")
    before = read_file(api, project_id)["commits"]

    api.client.post(f"/api/projects/{project_id}/abandon", json={})
    assert read_file(api, project_id)["commits"] == before


def test_a_revived_project_keeps_every_commit_it_had(api: Fixture) -> None:
    """One abandoned out of collage comes back with its sound set still frozen."""
    project_id = api.project_id("rust and rebar")
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    commit_all(api, project_id, "stored")
    api.client.post(f"/api/projects/{project_id}/abandon", json={})

    back = api.client.post(f"/api/projects/{project_id}/revive", json={})
    assert back.status_code == 200
    assert back.json()["column"] == "collage"
    assert back.json()["abandoned"] is None
    assert [c["column"] for c in back.json()["commits"]] == ["stored"]
    assert api.client.put(
        f"/api/projects/{project_id}/sounds/{api.hash_of('hat.wav')}"
    ).status_code == 409


def test_revive_takes_a_slot_and_is_refused_when_the_column_is_full(
    capped_api: Callable[[int], Fixture],
) -> None:
    """Reviving is not free. The cost is the slot, which is the right price."""
    api = capped_api(1)
    first = api.project_id("first")
    api.client.post(f"/api/projects/{first}/abandon", json={})
    api.make_project("second")

    refused = api.client.post(f"/api/projects/{first}/revive", json={})
    assert refused.status_code == 409
    assert refused.json()["detail"]["column"] == "stored"
    assert refused.json()["detail"]["overridable"] is True
    assert read_file(api, first)["abandoned"] is not None

    forced = api.client.post(f"/api/projects/{first}/revive", json={"override": True})
    assert forced.status_code == 200
    assert api.client.get("/api/board").json()["columns"][0]["over"] is True


def test_a_released_project_cannot_be_abandoned(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    commit_all(api, project_id, "enrich")
    assert api.client.post(f"/api/projects/{project_id}/abandon", json={}).status_code == 409


def test_an_abandoned_project_cannot_be_committed(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    api.client.post(f"/api/projects/{project_id}/abandon", json={})
    assert api.client.post(f"/api/projects/{project_id}/commit", json={}).status_code == 409


# --------------------------------------------------------------------- patch


def test_patch_writes_the_name_and_the_notes(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    response = api.client.patch(
        f"/api/projects/{project_id}", json={"name": "rust", "notes": "138 bpm"}
    )
    assert response.status_code == 200 and response.json()["name"] == "rust"
    assert read_file(api, project_id)["notes"] == "138 bpm"


def test_patch_refuses_to_move_a_project_between_columns(api: Fixture) -> None:
    """Otherwise every freeze is sidesteppable by editing one field."""
    project_id = api.project_id("rust and rebar")
    refused = api.client.patch(f"/api/projects/{project_id}", json={"column": "collage"})
    assert refused.status_code == 409
    assert "overridable" not in refused.json()["detail"]
    assert read_file(api, project_id)["column"] == "stored"


def test_patch_cannot_smuggle_a_column_in_beside_a_rename(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    refused = api.client.patch(
        f"/api/projects/{project_id}", json={"name": "rust", "column": "enrich"}
    )
    assert refused.status_code == 409
    assert read_file(api, project_id)["name"] == "rust and rebar"


# ------------------------------------------------------- the files always win


def test_a_hand_edited_file_is_picked_up_without_a_rebuild(api: Fixture) -> None:
    """The index is a cache. When the two disagree, the directory wins."""
    project_id = api.project_id("rust and rebar")
    assert api.client.get("/api/projects").json()["items"][0]["name"] == "rust and rebar"

    document = read_file(api, project_id)
    document["name"] = "edited by hand"
    write_file(api, project_id, document)

    assert api.client.get("/api/projects").json()["items"][0]["name"] == "edited by hand"


def test_a_file_deleted_by_hand_leaves_the_board(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    (api.projects_dir / f"{project_id}.json").unlink()
    assert api.client.get("/api/projects").json()["items"] == []
    assert api.client.get("/api/board").json()["columns"][0]["count"] == 0


def test_a_file_dropped_into_the_directory_appears(api: Fixture) -> None:
    document = model.new_document("dropped-in", "dropped in", model.utc_now())
    write_file(api, "dropped-in", document)
    body = api.client.get("/api/projects").json()
    assert [item["id"] for item in body["items"]] == ["dropped-in"]


def test_a_broken_file_is_reported_and_still_holds_its_slot(api: Fixture) -> None:
    """One junk key must not be a cap bypass that needs no override."""
    write_file(api, "broken-one", {"column": "stored", "nonsense": True})
    body = api.client.get("/api/projects").json()
    assert body["items"] == []
    assert body["unreadable"][0]["id"] == "broken-one"

    board = api.client.get("/api/board").json()
    assert board["columns"][0]["count"] == 1
    assert board["columns"][0]["unreadable"] == 1
    assert board["unreadable"] == 1


def test_a_file_that_is_not_json_at_all_is_reported(api: Fixture) -> None:
    (api.projects_dir).mkdir(parents=True, exist_ok=True)
    (api.projects_dir / "garbage.json").write_text("{not json", encoding="utf-8")
    body = api.client.get("/api/projects").json()
    assert body["unreadable"][0]["id"] == "garbage"
    assert "not JSON" in body["unreadable"][0]["problem"]
    # It names no column, so it holds no slot, but it is still counted.
    board = api.client.get("/api/board").json()
    assert board["columns"][0]["count"] == 0 and board["unreadable"] == 1


def test_a_broken_file_answers_200_with_its_reasons_not_404(api: Fixture) -> None:
    write_file(api, "broken-one", {"column": "stored"})
    body = api.client.get("/api/projects/broken-one").json()
    assert body["valid"] is False and body["summary"] is None
    assert body["issues"] and body["document"] == {"column": "stored"}


def test_a_document_whose_id_is_not_its_filename_is_refused(api: Fixture) -> None:
    """It would be reachable under two names and writable under neither."""
    document = model.new_document("some-other-id", "a project", model.utc_now())
    write_file(api, "on-disk-name", document)
    body = api.client.get("/api/projects/on-disk-name").json()
    assert body["valid"] is False
    assert any(issue["path"] == "id" for issue in body["issues"])


def test_a_tampered_sound_set_is_reported_as_unverified(api: Fixture) -> None:
    """The freeze is a fact that can be checked, not a rule the app keeps."""
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    commit_all(api, project_id, "stored")
    assert api.client.get(f"/api/projects/{project_id}").json()["summary"][
        "sound_set_verified"
    ] is True

    document = read_file(api, project_id)
    document["sounds"] = []
    write_file(api, project_id, document)
    assert api.client.get(f"/api/projects/{project_id}").json()["summary"][
        "sound_set_verified"
    ] is False


def test_the_cache_can_be_thrown_away_and_derived_again(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    api.client.get("/api/projects")

    conn = sqlite3.connect(api.db_path)
    conn.execute("DELETE FROM project")
    conn.commit()
    conn.close()

    body = api.client.get("/api/projects").json()
    assert [item["id"] for item in body["items"]] == [project_id]


def test_the_store_rebuilds_the_index_from_the_directory(
    tmp_path: Path, validator: Any
) -> None:
    from audio_browser.db import open_db

    store = ProjectStore(tmp_path / "projects", validator=validator, caps=Caps())
    at = model.utc_now()
    store.create("one", at=at)
    store.create("two", at=at)

    conn = open_db(tmp_path / "index.db")
    assert store.rebuild(conn, at=at) == 2
    rows = conn.execute("SELECT id, placement, valid FROM project ORDER BY id").fetchall()
    assert [row["placement"] for row in rows] == ["stored", "stored"]
    assert all(row["valid"] == 1 for row in rows)
    conn.close()
