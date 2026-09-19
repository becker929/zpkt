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


def commit_stored(fixture: Fixture, project_id: str) -> None:
    """Freeze the sound set and move the project to `collage`."""
    response = fixture.client.post(
        f"/api/projects/{project_id}/commit",
        json={"expect_column": "stored", "override": True},
    )
    assert response.status_code == 200, response.text


def region(file_hash: str, **fields: object) -> dict[str, Any]:
    """One region as the client sends it, with the spec's defaults."""
    return {
        "id": "r1",
        "hash": file_hash,
        "track": 0,
        "start_s": 0.1,
        "end_s": 0.4,
        "at_s": 0.0,
        "rate": 1.0,
        "gain": 1.0,
        "fade_in_s": 0.0,
        "fade_out_s": 0.0,
        **fields,
    }


def stamp(fixture: Fixture, project_id: str, file_hash: str) -> dict[str, Any]:
    """Put a one-region collage on a project and return the response body."""
    response = fixture.client.put(
        f"/api/projects/{project_id}/collage", json={"regions": [region(file_hash)]}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def commit_collage(fixture: Fixture, project_id: str) -> dict[str, Any]:
    """Freeze the collage and move the project to `enrich`."""
    response = fixture.client.post(
        f"/api/projects/{project_id}/commit",
        json={"expect_column": "collage", "override": True},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def in_collage(fixture: Fixture, name: str, file_hash: str, **body: object) -> str:
    """A project holding one sound, committed out of `stored`."""
    project_id = fixture.project_id(name, **body)
    fixture.client.put(f"/api/projects/{project_id}/sounds/{file_hash}")
    commit_stored(fixture, project_id)
    return project_id


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


def test_the_later_stage_says_its_artifact_is_not_real_yet() -> None:
    """enrich has no view, so its digest is a placeholder and says so."""
    artifact = model.commit_artifact("p", ["a" * 64], "enrich")
    assert artifact.real is False
    assert artifact.digest != model.commit_artifact("q", ["a" * 64], "enrich").digest


def test_the_board_ends_at_enrich_and_says_nothing_follows_it() -> None:
    """`enrich` is the placeholder column: a cap, no view, nowhere to go."""
    assert model.COLUMNS == ("stored", "collage", "enrich")
    assert model.next_placement("stored") == "collage"
    assert model.next_placement("collage") == "enrich"
    assert model.next_placement("enrich") is None
    assert model.next_planned("enrich") is None
    assert model.is_column("enrich")
    assert not model.is_column("released")


def test_a_project_is_encumbered_past_the_threshold_and_not_at_it() -> None:
    """Past sixteen you are collecting, not building."""
    assert model.DEFAULT_ENCUMBRANCE == 16
    assert not model.is_encumbered(16)
    assert model.is_encumbered(17)
    assert model.is_encumbered(3, threshold=2)


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

    assert model.schema_accepts(validator, document), "the schema alone lets this through"
    issues = model.check_project(validator, document)
    assert [i.path for i in issues] == ["sounds"]
    assert "set" in issues[0].message


def test_updated_before_created_is_refused(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["updated_at"] = "2026-09-15T21:04:00Z"
    assert model.schema_accepts(validator, document)
    assert [i.path for i in model.check_project(validator, document)] == ["updated_at"]


def test_a_commit_dated_before_the_project_is_refused(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["column"] = "collage"
    document["commits"] = [
        {"column": "stored", "at": "2026-01-01T00:00:00Z", "digest": "a" * 64}
    ]
    assert model.schema_accepts(validator, document)
    assert [i.path for i in model.check_project(validator, document)] == ["commits.0.at"]


def test_an_abandonment_that_disagrees_with_the_column_is_refused(validator: Any) -> None:
    """Revive and the board would otherwise disagree about the same project."""
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["abandoned"] = {
        "at": "2026-09-17T00:00:00Z", "from": "collage", "reason": ""
    }
    assert model.schema_accepts(validator, document)
    assert [i.path for i in model.check_project(validator, document)] == ["abandoned.from"]


def test_the_chain_is_tied_to_the_column_by_the_schema_itself(validator: Any) -> None:
    """A collage project without a stored commit is not a document at all.

    This is what makes "the sound set is frozen from collage onwards" a property
    of the format rather than a rule the app promises to keep.
    """
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    document["column"] = "collage"
    assert not model.schema_accepts(validator, document)
    assert model.check_project(validator, document)


# ------------------------------------------------------------------ the API


def test_the_board_starts_empty_with_the_configured_cap(api: Fixture) -> None:
    board = api.client.get("/api/board").json()
    assert [c["column"] for c in board["columns"]] == ["stored", "collage", "enrich"]
    assert all(c["cap"] == 1 and c["count"] == 0 and not c["over"] for c in board["columns"])
    assert board["encumbrance"] == 16
    assert board == {**board, "released": 0, "abandoned": 0, "unreadable": 0}


def test_an_empty_board_is_not_blocked(api: Fixture) -> None:
    """Nothing is stuck. There is nothing there, and the answer is to start."""
    board = api.client.get("/api/board").json()
    assert board["blocked"] is False
    assert board["blocks"] == []
    assert board["detail"] is None


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
    second = api.project_id("rust and rebar", override=True)
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
    api: Fixture,
) -> None:
    """Friction, not restriction: it states the cap and offers a way through.

    One lane. A second uncommitted project in `stored` would mean choosing which
    project a swiped sound goes into, and there is no such choice.
    """
    api.make_project("first")
    refused = api.client.post("/api/projects", json={"name": "second"})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["column"] == "stored" and detail["cap"] == 1 and detail["count"] == 1
    assert detail["overridable"] is True


def test_an_override_gets_through_and_the_column_stays_visibly_over(
    api: Fixture,
) -> None:
    api.make_project("first")
    api.make_project("second", override=True)
    column = api.client.get("/api/board").json()["columns"][0]
    assert column["count"] == 2 and column["cap"] == 1 and column["over"] is True


def test_a_cap_of_zero_closes_the_column(capped_api: Callable[..., Fixture]) -> None:
    api = capped_api(0)
    assert api.client.post("/api/projects", json={"name": "first"}).status_code == 409
    api.make_project("first", override=True)
    assert api.client.get("/api/board").json()["columns"][0]["over"] is True


def test_two_simultaneous_creates_cannot_both_pass_one_cap_check(
    api: Fixture,
) -> None:
    """Counting and then writing is a read-then-write, and two interleave.

    Without a lock both requests count zero against a cap of one, both find
    room, and the column ends up holding two with nobody having overridden
    anything. The mock backend was single threaded and could not show this.
    """
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


# --------------------------------------------------------------- encumbrance
#
# Friction, not restriction. Adding still succeeds, the mark is reported, and it
# clears when the count comes back down.


def test_a_project_past_the_threshold_is_marked_and_still_takes_sounds(
    capped_api: Callable[..., Fixture],
) -> None:
    api = capped_api(1, encumbrance=2)
    project_id = api.project_id("rust and rebar")

    marks = []
    for name in ("kick.wav", "hat.wav", "loop.mp3"):
        added = api.client.put(
            f"/api/projects/{project_id}/sounds/{api.hash_of(name)}"
        )
        assert added.status_code == 200, added.text
        marks.append(added.json()["summary"]["encumbered"])

    # Two is the threshold, so two is not past it. The third one is.
    assert marks == [False, False, True]
    assert api.client.get(f"/api/projects/{project_id}").json()["summary"][
        "encumbered"
    ] is True


def test_the_mark_clears_when_the_count_comes_back_down(
    capped_api: Callable[..., Fixture],
) -> None:
    api = capped_api(1, encumbrance=2)
    project_id = api.project_id("rust and rebar")
    for name in ("kick.wav", "hat.wav", "loop.mp3"):
        api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of(name)}")

    dropped = api.client.delete(
        f"/api/projects/{project_id}/sounds/{api.hash_of('loop.mp3')}"
    )
    assert dropped.json()["summary"]["encumbered"] is False


def test_the_board_states_the_threshold_it_is_marking_against(
    capped_api: Callable[..., Fixture],
) -> None:
    """The interface draws the server's number, never one of its own."""
    api = capped_api(1, encumbrance=4)
    assert api.client.get("/api/board").json()["encumbrance"] == 4


def test_every_project_view_carries_the_mark(
    capped_api: Callable[..., Fixture],
) -> None:
    """It is visible every time the project is on screen, not only on the board."""
    api = capped_api(1, encumbrance=1)
    project_id = api.project_id("rust and rebar")
    for name in ("kick.wav", "hat.wav"):
        api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of(name)}")

    assert api.client.get("/api/projects").json()["items"][0]["encumbered"] is True
    assert api.client.get(f"/api/projects/{project_id}").json()["summary"][
        "encumbered"
    ] is True
    assert api.client.get("/api/swipe").json()["project"]["encumbered"] is True
    frozen = api.client.post(
        f"/api/projects/{project_id}/commit", json={"expect_column": "stored"}
    )
    assert frozen.json()["summary"]["encumbered"] is True


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


def test_a_full_next_column_gates_promotion(api: Fixture) -> None:
    """You cannot keep gathering material while the collage bench is full."""
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


def test_committing_out_of_the_last_column_leaves_the_project_where_it_is(
    api: Fixture,
) -> None:
    """It holds its lane rather than vanishing.

    Releasing it here would free the lane, and a pipeline whose last column
    empties itself is not a constraint at all. Abandon is the one way out, and
    that is the price it is meant to be.
    """
    project_id = in_collage(api, "rust and rebar", api.hash_of("kick.wav"))
    stamp(api, project_id, api.hash_of("kick.wav"))
    commit_collage(api, project_id)

    refused = api.client.post(
        f"/api/projects/{project_id}/commit",
        json={"expect_column": "enrich", "override": True},
    )
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "missing_column" not in detail, "nothing is planned after enrich"
    assert "overridable" not in detail, "no override conjures a column"

    on_disk = read_file(api, project_id)
    assert on_disk["column"] == "enrich"
    assert [c["column"] for c in on_disk["commits"]] == ["stored", "collage"]

    board = api.client.get("/api/board").json()
    assert board["released"] == 0
    assert board["columns"][2]["count"] == 1


def test_the_board_says_why_nothing_can_move_and_names_what_is_missing(
    api: Fixture,
) -> None:
    """The deadlock in the specification, walked from an empty board.

    A project reaches enrich, which has nowhere to go. A second reaches collage
    and cannot commit because enrich is full. A third is born in stored and
    cannot commit because collage is full. Nothing can move, and the board says
    so.
    """
    first = in_collage(api, "first", api.hash_of("kick.wav"))
    stamp(api, first, api.hash_of("kick.wav"))
    commit_collage(api, first)

    # One column occupied, and it is the last one: already blocked.
    board = api.client.get("/api/board").json()
    assert board["blocked"] is True
    assert [b["reason"] for b in board["blocks"]] == ["next_column_missing"]
    assert board["blocks"][0]["column"] == "enrich"
    assert board["blocks"][0]["missing_column"] is None

    second = in_collage(api, "second", api.hash_of("hat.wav"))
    stamp(api, second, api.hash_of("hat.wav"))
    refused = api.client.post(
        f"/api/projects/{second}/commit", json={"expect_column": "collage"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["column"] == "enrich"

    third = api.project_id("third")
    api.client.put(f"/api/projects/{third}/sounds/{api.hash_of('loop.mp3')}")
    refused = api.client.post(
        f"/api/projects/{third}/commit", json={"expect_column": "stored"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["column"] == "collage"

    board = api.client.get("/api/board").json()
    assert board["blocked"] is True
    assert [(b["column"], b["reason"]) for b in board["blocks"]] == [
        ("stored", "next_column_full"),
        ("collage", "next_column_full"),
        ("enrich", "next_column_missing"),
    ]
    assert [b["overridable"] for b in board["blocks"]] == [True, True, False]
    assert board["blocks"][2]["next_column"] is None
    assert board["detail"] is not None
    assert board["detail"].startswith("Nothing can move.")
    assert "enrich" in board["detail"]


def test_a_collage_project_is_not_blocked_while_enrich_has_room(api: Fixture) -> None:
    """The deadlock the board used to report at collage is gone. It moved."""
    project_id = in_collage(api, "rust and rebar", api.hash_of("kick.wav"))
    board = api.client.get("/api/board").json()
    assert board["blocked"] is False
    assert board["blocks"] == []


def test_abandoning_is_the_one_way_out_of_the_deadlock(api: Fixture) -> None:
    """The constraint bites, and there is exactly one pressure valve."""
    first = api.project_id("first")
    api.client.put(f"/api/projects/{first}/sounds/{api.hash_of('kick.wav')}")
    api.client.post(f"/api/projects/{first}/commit", json={"expect_column": "stored"})
    second = api.project_id("second")
    api.client.put(f"/api/projects/{second}/sounds/{api.hash_of('hat.wav')}")
    assert api.client.post(
        f"/api/projects/{second}/commit", json={"expect_column": "stored"}
    ).status_code == 409

    api.client.post(f"/api/projects/{first}/abandon", json={"reason": "dead idea"})

    freed = api.client.post(
        f"/api/projects/{second}/commit", json={"expect_column": "stored"}
    )
    assert freed.status_code == 200
    assert freed.json()["summary"]["column"] == "collage"


def test_only_an_occupied_column_is_reported_as_blocked(api: Fixture) -> None:
    """An empty column holds nothing, so there is nothing there to be stuck."""
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")

    board = api.client.get("/api/board").json()
    assert board["blocks"] == []  # collage is empty, so stored can commit
    assert board["blocked"] is False


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
    commit_stored(api, project_id)
    before = read_file(api, project_id)["commits"]

    api.client.post(f"/api/projects/{project_id}/abandon", json={})
    assert read_file(api, project_id)["commits"] == before


def test_a_revived_project_keeps_every_commit_it_had(api: Fixture) -> None:
    """One abandoned out of collage comes back with its sound set still frozen."""
    project_id = api.project_id("rust and rebar")
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    commit_stored(api, project_id)
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
    api: Fixture,
) -> None:
    """Reviving is not free. The cost is the slot, which is the right price."""
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


def test_a_project_in_the_last_column_can_still_be_abandoned(api: Fixture) -> None:
    """It is the only way to free that lane, so it must keep working there."""
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    commit_stored(api, project_id)

    left = api.client.post(f"/api/projects/{project_id}/abandon", json={})
    assert left.status_code == 200
    assert left.json()["abandoned"]["from"] == "collage"
    board = api.client.get("/api/board").json()
    assert board["columns"][1]["count"] == 0 and board["abandoned"] == 1
    assert board["blocked"] is False


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
    commit_stored(api, project_id)
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

    store = ProjectStore(
        tmp_path / "projects", validator=validator, caps=Caps.uniform(2)
    )
    at = model.utc_now()
    store.create("one", at=at)
    store.create("two", at=at)

    conn = open_db(tmp_path / "index.db")
    assert store.rebuild(conn, at=at) == 2
    rows = conn.execute("SELECT id, placement, valid FROM project ORDER BY id").fetchall()
    assert [row["placement"] for row in rows] == ["stored", "stored"]
    assert all(row["valid"] == 1 for row in rows)
    conn.close()


# ------------------------------------------------------------------- collage
#
# The first tracer bullet: choose a sound, stamp it as a region, freeze it.
# Nothing here reads or removes audio. The description is a JSON field.


def collage_document(fixture: Fixture, project_id: str) -> dict[str, Any] | None:
    """The `collage` field straight off disk."""
    value = read_file(fixture, project_id).get("collage")
    return dict(value) if isinstance(value, dict) else None


def test_a_new_project_carries_a_null_collage(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    on_disk = read_file(api, project_id)
    assert "collage" in on_disk and on_disk["collage"] is None


def test_a_stamped_region_lands_in_the_file_and_reads_back(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)

    body = stamp(api, project_id, kick)
    assert body["frozen"] is False
    assert body["collage"] == {"regions": [region(kick)]}
    assert collage_document(api, project_id) == {"regions": [region(kick)]}

    detail = api.client.get(f"/api/projects/{project_id}").json()
    assert detail["document"]["collage"] == {"regions": [region(kick)]}


def test_put_replaces_the_whole_description(api: Fixture) -> None:
    """Whole, not merged. A region left out is gone."""
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    api.client.put(
        f"/api/projects/{project_id}/collage",
        json={"regions": [region(kick, id="r1"), region(kick, id="r2", track=1)]},
    )
    stamp(api, project_id, kick)
    regions = (collage_document(api, project_id) or {})["regions"]
    assert [r["id"] for r in regions] == ["r1"]


def test_the_defaults_are_filled_in_so_a_stamp_is_three_seconds(api: Fixture) -> None:
    """The document always carries all ten keys, whatever the client sent."""
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    response = api.client.put(
        f"/api/projects/{project_id}/collage",
        json={
            "regions": [
                {"id": "r1", "hash": kick, "track": 0, "start_s": 0.1, "end_s": 0.4, "at_s": 2.0}
            ]
        },
    )
    assert response.status_code == 200, response.text
    written = (collage_document(api, project_id) or {})["regions"][0]
    assert set(written) == set(model.REGION_FIELDS)
    assert written["rate"] == 1.0 and written["gain"] == 1.0
    assert written["fade_in_s"] == 0.0 and written["fade_out_s"] == 0.0


@pytest.mark.parametrize(
    "bad,path",
    [
        ({"hash": "b" * 64}, "hash"),  # not in the frozen set
        ({"start_s": 0.4, "end_s": 0.4}, "end_s"),
        ({"start_s": 0.5, "end_s": 0.4}, "end_s"),
        ({"track": -1}, "track"),
        ({"rate": 0}, "rate"),
        ({"gain": -0.1}, "gain"),
        ({"at_s": -1}, "at_s"),
    ],
)
def test_a_region_that_breaks_a_rule_is_refused_and_not_written(
    api: Fixture, bad: dict[str, Any], path: str
) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    response = api.client.put(
        f"/api/projects/{project_id}/collage", json={"regions": [region(kick, **bad)]}
    )
    assert response.status_code == 422, response.text
    assert path in response.text
    assert collage_document(api, project_id) is None


def test_a_region_may_only_cut_from_the_frozen_set(api: Fixture) -> None:
    """hat is in the library and is not in this project. Collage cannot add it."""
    kick, hat = api.hash_of("kick.wav"), api.hash_of("hat.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    refused = api.client.put(
        f"/api/projects/{project_id}/collage", json={"regions": [region(hat)]}
    )
    assert refused.status_code == 422
    assert "frozen set" in refused.json()["detail"]["detail"]


def test_region_ids_are_unique(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    refused = api.client.put(
        f"/api/projects/{project_id}/collage",
        json={"regions": [region(kick, id="r1"), region(kick, id="r1", track=1)]},
    )
    assert refused.status_code == 422
    assert "unique" in refused.json()["detail"]["detail"]


def test_a_region_with_an_unknown_key_is_refused(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    refused = api.client.put(
        f"/api/projects/{project_id}/collage",
        json={"regions": [region(kick, seconds_label="12s")]},
    )
    assert refused.status_code == 422


def test_a_project_in_stored_cannot_hold_a_collage(api: Fixture) -> None:
    """No frozen set yet, so nothing settled to cut from. 409, not overridable."""
    kick = api.hash_of("kick.wav")
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    refused = api.client.put(
        f"/api/projects/{project_id}/collage", json={"regions": [region(kick)]}
    )
    assert refused.status_code == 409
    assert "overridable" not in refused.json()["detail"]
    assert "stored" in refused.json()["detail"]["detail"]
    assert collage_document(api, project_id) is None


def test_an_abandoned_project_cannot_be_cut(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    api.client.post(f"/api/projects/{project_id}/abandon", json={})
    refused = api.client.put(
        f"/api/projects/{project_id}/collage", json={"regions": [region(kick)]}
    )
    assert refused.status_code == 409


def test_an_unknown_project_is_a_404(api: Fixture) -> None:
    response = api.client.put(
        "/api/projects/no-such-project/collage",
        json={"regions": [region("a" * 64)]},
    )
    assert response.status_code == 404


def test_a_file_from_before_the_field_existed_reads_as_null(api: Fixture) -> None:
    """HW011 was written without the key. Absent means the same as null."""
    document = model.new_document("older", "older", "2026-09-16T21:04:00Z")
    del document["collage"]
    write_file(api, "older", document)
    detail = api.client.get("/api/projects/older").json()
    assert detail["valid"] is True
    assert "collage" not in detail["document"]
    assert model.collage_of(detail["document"]) is None


def test_a_hand_written_collage_in_stored_makes_the_file_unreadable(
    api: Fixture,
) -> None:
    document = model.new_document("edited", "edited", "2026-09-16T21:04:00Z")
    document["collage"] = {"regions": []}
    write_file(api, "edited", document)
    body = api.client.get("/api/projects").json()
    assert body["unreadable"][0]["id"] == "edited"
    assert "collage" in body["unreadable"][0]["problem"]


# ---------------------------------------------------- committing out of collage


def test_committing_out_of_collage_freezes_the_description(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    stamp(api, project_id, kick)

    body = commit_collage(api, project_id)
    assert body["commit"]["column"] == "collage"
    assert body["artifact_real"] is True
    assert body["summary"]["column"] == "enrich"
    expected = model.digest_of(model.collage_input({"regions": [region(kick)]}))
    assert body["commit"]["digest"] == expected

    on_disk = read_file(api, project_id)
    assert on_disk["column"] == "enrich"
    assert [c["column"] for c in on_disk["commits"]] == ["stored", "collage"]
    assert on_disk["collage"] == {"regions": [region(kick)]}


def test_the_description_is_refused_once_committed(api: Fixture) -> None:
    """The field is what the commit froze. Freezing is one way."""
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    stamp(api, project_id, kick)
    commit_collage(api, project_id)

    refused = api.client.put(
        f"/api/projects/{project_id}/collage",
        json={"regions": [region(kick, id="r9")]},
    )
    assert refused.status_code == 409
    assert "overridable" not in refused.json()["detail"]
    assert "frozen" in refused.json()["detail"]["detail"]
    assert collage_document(api, project_id) == {"regions": [region(kick)]}


def test_an_empty_collage_cannot_be_frozen(api: Fixture) -> None:
    """422, and no override, as with an empty sound set."""
    kick = api.hash_of("kick.wav")
    project_id = in_collage(api, "rust and rebar", kick)
    for description in (None, {"regions": []}):
        if description is not None:
            put = api.client.put(f"/api/projects/{project_id}/collage", json=description)
            assert put.status_code == 200, put.text
        refused = api.client.post(
            f"/api/projects/{project_id}/commit",
            json={"expect_column": "collage", "override": True},
        )
        assert refused.status_code == 422, refused.text
        assert read_file(api, project_id)["column"] == "collage"


def test_a_full_enrich_gates_promotion_out_of_collage(api: Fixture) -> None:
    kick, hat = api.hash_of("kick.wav"), api.hash_of("hat.wav")
    blocker = in_collage(api, "blocker", kick)
    stamp(api, blocker, kick)
    commit_collage(api, blocker)

    waiting = in_collage(api, "waiting", hat, override=True)
    stamp(api, waiting, hat)
    refused = api.client.post(
        f"/api/projects/{waiting}/commit", json={"expect_column": "collage"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["column"] == "enrich"
    assert refused.json()["detail"]["overridable"] is True

    commit_collage(api, waiting)
    assert api.client.get("/api/board").json()["columns"][2]["over"] is True


# ------------------------------------------------- the canonical serialisation
#
# Committing out of collage digests one string. Two descriptions that mean the
# same thing must produce the same string, or a digest would depend on which
# tab wrote the file.


def test_the_canonical_text_is_sorted_fixed_point_and_whitespace_free() -> None:
    text = model.collage_input(
        {
            "regions": [
                {
                    "id": "r1",
                    "hash": "a" * 64,
                    "track": 0,
                    "start_s": 41.2,
                    "end_s": 47.9,
                    "at_s": 12,
                    "rate": 1,
                    "gain": 1.0,
                    "fade_in_s": 0,
                    "fade_out_s": 0.0,
                }
            ]
        }
    )
    assert text == (
        '{"regions":[{"at_s":12.000000,"end_s":47.900000,"fade_in_s":0.000000,'
        '"fade_out_s":0.000000,"gain":1.000000,"hash":"' + "a" * 64 + '",'
        '"id":"r1","rate":1.000000,"start_s":41.200000,"track":0}]}'
    )


def test_two_equivalent_descriptions_digest_identically() -> None:
    """Key order, region order, `1` against `1.0`, and float noise all vanish."""
    one = {
        "regions": [
            {
                "id": "r2", "hash": "b" * 64, "track": 1, "start_s": 0.1 + 0.2,
                "end_s": 5, "at_s": 0, "rate": 1, "gain": 0.5, "fade_in_s": 0,
                "fade_out_s": 0,
            },
            {
                "id": "r1", "hash": "a" * 64, "track": 0, "start_s": 41.2,
                "end_s": 47.9, "at_s": 12.0, "rate": 1.0, "gain": 1.0,
                "fade_in_s": 0.0, "fade_out_s": 0.0,
            },
        ]
    }
    two = {
        "regions": [
            {
                "fade_out_s": 0.0, "fade_in_s": 0.0, "gain": 1.0, "rate": 1.0,
                "at_s": 12, "end_s": 47.9, "start_s": 41.2, "track": 0,
                "hash": "a" * 64, "id": "r1",
            },
            {
                "gain": 0.5, "fade_in_s": 0.0, "fade_out_s": -0.0, "rate": 1.0,
                "at_s": 0.0, "end_s": 5.0, "start_s": 0.3, "track": 1,
                "hash": "b" * 64, "id": "r2",
            },
        ]
    }
    first = model.commit_artifact("p", ["a" * 64, "b" * 64], "collage", collage=one)
    second = model.commit_artifact("p", ["a" * 64, "b" * 64], "collage", collage=two)
    assert first.real is True
    assert first.input == second.input
    assert first.digest == second.digest

    moved = {**two, "regions": [{**two["regions"][0], "at_s": 12.5}, two["regions"][1]]}
    third = model.commit_artifact("p", ["a" * 64, "b" * 64], "collage", collage=moved)
    assert third.digest != first.digest


def test_the_digest_is_stable_across_key_order_through_the_api(api: Fixture) -> None:
    """The same walk as above, but through PUT and commit on two projects."""
    kick = api.hash_of("kick.wav")
    forwards = region(kick)
    backwards = dict(reversed(list(forwards.items())))
    assert list(forwards) != list(backwards)

    digests = []
    for name, description in (("one", forwards), ("two", backwards)):
        project_id = in_collage(api, name, kick, override=True)
        put = api.client.put(
            f"/api/projects/{project_id}/collage", json={"regions": [description]}
        )
        assert put.status_code == 200, put.text
        digests.append(commit_collage(api, project_id)["commit"]["digest"])
    assert digests[0] == digests[1]


# ---------------------------------------------------- the schema and the spec
#
# The schema is generated from the Zod declarations on its own schedule. Until
# it carries `collage`, Python is the authority for that field. Once it does,
# it has to say what the specification says, or the two languages would accept
# different files.


def test_python_owns_the_field_until_the_schema_learns_it(validator: Any) -> None:
    document = model.new_document("p", "p", "2026-09-16T21:04:00Z")
    assert not model.check_project(validator, document)
    if not model.schema_declares_collage(validator):
        # The schema alone would refuse the key. The shim takes it out for the
        # schema's benefit and the Python rules still apply.
        assert not validator.is_valid(document)
        document["collage"] = {"regions": []}
        assert [i.path for i in model.check_project(validator, document)] == ["collage"]


def test_a_regenerated_schema_agrees_with_the_specification(validator: Any) -> None:
    """Fails loudly, naming the disagreement, rather than following either side."""
    if not model.schema_declares_collage(validator):
        pytest.skip("schemas/project.schema.json does not declare collage yet")
    schema = validator.schema
    for index, branch in enumerate(schema["anyOf"]):
        declared = branch["properties"]["collage"]
        column = branch["properties"]["column"].get("const", "?")
        # Resolve a $ref into the branch it points at, so every branch is read
        # the same way whether it repeats the shape or refers to it.
        while "$ref" in declared:
            target: Any = schema
            for part in declared["$ref"].lstrip("#/").split("/"):
                target = target[int(part)] if isinstance(target, list) else target[part]
            declared = target
        options = declared.get("anyOf", [declared])
        nullable = any(o.get("type") == "null" for o in options)
        objects = [o for o in options if o.get("type") == "object"]
        assert nullable, f"branch {index} ({column}): collage must be nullable"
        if column == "stored":
            continue  # the spec says stored holds none; null alone is fine
        assert objects, f"branch {index} ({column}): collage must allow an object"
        regions = objects[0]["properties"]["regions"]["items"]
        assert set(regions.get("required", [])) == set(model.REGION_FIELDS), (
            f"branch {index} ({column}): the schema's region keys are "
            f"{sorted(regions.get('required', []))}; the specification's are "
            f"{sorted(model.REGION_FIELDS)}"
        )
