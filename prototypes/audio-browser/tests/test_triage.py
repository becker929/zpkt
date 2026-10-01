"""Triage: soft delete, lists, bulk edit, and the progress counter.

Everything here runs against the generated collection in the ``api`` fixture.
No test reads the real library, and no test may leave a file changed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from audio_browser.server.models import MAX_BULK_HASHES
from conftest import Fixture, peek, tree_snapshot


def count(db_path: Path, table: str) -> int:
    return int(peek(db_path, f"SELECT COUNT(*) AS n FROM {table}")["n"])




# --------------------------------------------------------------- soft delete


def test_discarding_a_sound_hides_it_from_the_default_list(api: Fixture) -> None:
    """The point of discarding is to stop seeing it, so the default view obeys."""
    kick = api.hash_of("kick.wav")
    assert api.client.get("/api/files").json()["total"] == 3

    state = api.client.put(f"/api/files/{kick}/deleted").json()
    assert state["deleted"] is True
    assert state["deleted_at"] is not None

    body = api.client.get("/api/files").json()
    assert body["total"] == 2
    assert kick not in {item["hash"] for item in body["items"]}


def test_the_discarded_pile_is_asked_for_by_name(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/deleted")

    only = api.client.get("/api/files?deleted=true").json()
    assert [item["hash"] for item in only["items"]] == [kick]
    assert only["items"][0]["deleted"] is True

    both = api.client.get("/api/files?deleted=any").json()
    assert both["total"] == 3


def test_deleted_is_one_of_three_words(api: Fixture) -> None:
    """A typo must not silently mean 'show everything'."""
    assert api.client.get("/api/files?deleted=maybe").status_code == 422


def test_restore_puts_it_back(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/deleted", json={"note": "muddy"})
    state = api.client.delete(f"/api/files/{kick}/deleted").json()
    assert state["deleted"] is False
    assert state["deleted_at"] is None
    assert api.client.get("/api/files").json()["total"] == 3


def test_restoring_something_that_was_never_discarded_is_fine(api: Fixture) -> None:
    """Undo is pressed twice all the time. It should not be an error."""
    response = api.client.delete(f"/api/files/{api.hash_of('hat.wav')}/deleted")
    assert response.status_code == 200
    assert response.json()["deleted"] is False


def test_the_discard_note_survives_a_second_discard(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/deleted", json={"note": "clipping"})
    again = api.client.put(f"/api/files/{kick}/deleted").json()
    assert again["note"] == "clipping"


def test_discarding_keys_on_the_hash_so_every_copy_goes(api: Fixture) -> None:
    """Two paths hold these bytes. One decision covers both."""
    kick = api.hash_of("kick.wav")
    state = api.client.put(f"/api/files/{kick}/deleted").json()
    assert state["alias_count"] == 2
    assert count(api.db_path, "alias") == 6  # every path is still indexed


def test_discarding_removes_no_file(api: Fixture) -> None:
    """The whole feature is a row. This is the test that says so."""
    before = tree_snapshot(api.tmp_path / "source")
    api.client.put(f"/api/files/{api.hash_of('kick.wav')}/deleted")
    assert tree_snapshot(api.tmp_path / "source") == before
    # ... and the sound still plays, because the bytes never moved.
    assert api.client.get(
        f"/api/files/{api.hash_of('kick.wav')}/stream"
    ).status_code == 200


def test_soft_delete_and_the_deletion_table_are_different_things(
    api: Fixture,
) -> None:
    """A path swept from disk and a sound the user rejected are not the same.

    Both can be true of one sound at once, and each must stay readable on its
    own. The detail view reports them in separate fields.
    """
    kick = api.hash_of("kick.wav")
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO deletion (hash, path, root, deleted_at, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        (kick, "/gone/kick.wav", "copy", "2026-01-01T00:00:00+00:00", "redundant copy"),
    )
    conn.commit()
    conn.close()

    api.client.put(f"/api/files/{kick}/deleted", json={"note": "too boomy"})
    detail = api.client.get(f"/api/files/{kick}").json()

    assert detail["deleted"] is True
    assert detail["delete_note"] == "too boomy"
    assert [d["path"] for d in detail["deleted_sightings"]] == ["/gone/kick.wav"]
    assert detail["deleted_sightings"][0]["reason"] == "redundant copy"

    # Restoring the sound leaves the disk history alone.
    api.client.delete(f"/api/files/{kick}/deleted")
    after = api.client.get(f"/api/files/{kick}").json()
    assert after["deleted"] is False
    assert len(after["deleted_sightings"]) == 1


def test_discarding_an_unknown_hash_is_a_404(api: Fixture) -> None:
    assert api.client.put(f"/api/files/{'0' * 64}/deleted").status_code == 404


# ---------------------------------------------------------------------- bulk


def test_bulk_discard_reports_what_it_changed(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    api.client.put(f"/api/files/{hashes[0]}/deleted")  # already discarded

    body = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "delete"}
    ).json()
    assert body["requested"] == 3
    assert body["matched"] == 3
    assert body["changed"] == 2
    assert body["unchanged"] == 1
    assert body["skipped"] == 0
    assert count(api.db_path, "soft_delete") == 3


def test_the_only_bulk_actions_left_are_the_two_answers(api: Fixture) -> None:
    """Starring and filing in bulk are gone, along with the routes behind them."""
    for gone in ("star", "unstar", "add_to_list", "remove_from_list"):
        response = api.client.post(
            "/api/bulk", json={"hashes": [api.hash_of("kick.wav")], "action": gone}
        )
        assert response.status_code == 422, gone
    assert count(api.db_path, "favorite") == 0


def test_bulk_skips_hashes_this_index_does_not_know(api: Fixture) -> None:
    """A selection can be older than the last rescan. That is not an error."""
    hashes = [api.hash_of("kick.wav"), "0" * 64, "f" * 64]
    body = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "delete"}
    ).json()
    assert body["matched"] == 1
    assert body["skipped"] == 2
    assert body["changed"] == 1
    assert count(api.db_path, "soft_delete") == 1


def test_bulk_ignores_repeated_hashes(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    body = api.client.post(
        "/api/bulk", json={"hashes": [kick, kick, kick], "action": "delete"}
    ).json()
    assert body["requested"] == 3
    assert body["unique"] == 1
    assert body["changed"] == 1


def test_bulk_delete_then_restore_round_trips(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    before = tree_snapshot(api.tmp_path / "source")

    api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    assert api.client.get("/api/files").json()["total"] == 0
    assert api.client.get("/api/files?deleted=true").json()["total"] == 3

    restored = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "restore"}
    ).json()
    assert restored["changed"] == 3
    assert api.client.get("/api/files").json()["total"] == 3
    assert tree_snapshot(api.tmp_path / "source") == before


def test_an_unknown_action_is_refused(api: Fixture) -> None:
    response = api.client.post(
        "/api/bulk", json={"hashes": [api.hash_of("kick.wav")], "action": "burn"}
    )
    assert response.status_code == 422


def test_a_bulk_hash_gets_the_same_gate_as_a_path_parameter(api: Fixture) -> None:
    """A batch is not a back door. Every element is checked the same way."""
    for hostile in ("../../etc/passwd", "/etc/passwd", "' OR 1=1 --", "A" * 64):
        response = api.client.post(
            "/api/bulk",
            json={"hashes": [api.hash_of("kick.wav"), hostile], "action": "delete"},
        )
        assert response.status_code == 400, hostile
        assert "/etc/passwd" not in response.text
    # Nothing from the refused batch was applied, not even the valid hash.
    assert count(api.db_path, "soft_delete") == 0


def test_the_batch_is_capped(api: Fixture) -> None:
    """A thousand is a screenful of work many times over, and bounds the lock."""
    too_many = ["0" * 63 + "a"] * (MAX_BULK_HASHES + 1)
    response = api.client.post(
        "/api/bulk", json={"hashes": too_many, "action": "delete"}
    )
    assert response.status_code == 422


def test_an_empty_batch_does_nothing_quietly(api: Fixture) -> None:
    body = api.client.post("/api/bulk", json={"hashes": [], "action": "delete"}).json()
    assert body["changed"] == 0
    assert body["matched"] == 0


def test_a_batch_that_fails_partway_leaves_nothing_behind(api: Fixture) -> None:
    """The transaction boundary, tested by breaking the write mid-batch.

    A trigger refuses one hash out of three. SQLite aborts the statement, the
    route rolls back, and the two rows that would otherwise have landed are
    gone with it. A half-applied batch of a thousand is not something anyone
    could repair by hand, so there must be no such state to repair.
    """
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "CREATE TRIGGER refuse_one BEFORE INSERT ON soft_delete "
        f"WHEN new.hash = '{hashes[1]}' "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    conn.commit()
    conn.close()

    try:
        with pytest.raises(sqlite3.IntegrityError):
            api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    finally:
        conn = sqlite3.connect(api.db_path)
        conn.execute("DROP TRIGGER refuse_one")
        conn.commit()
        conn.close()

    assert count(api.db_path, "soft_delete") == 0

    # The connection is usable again once the batch has rolled back.
    body = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "delete"}
    ).json()
    assert body["changed"] == 3


def test_a_bulk_action_never_touches_the_filesystem(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    before = {r: tree_snapshot(api.tmp_path / r) for r in ("source", "copy")}
    api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    after = {r: tree_snapshot(api.tmp_path / r) for r in ("source", "copy")}
    assert after == before


# -------------------------------------------------------------------- triage


def test_nothing_answered_is_nothing_triaged(api: Fixture) -> None:
    body = api.client.get("/api/triage").json()
    assert body == {
        "total": 3,
        "triaged": 0,
        "untriaged": 3,
        "percent": 0.0,
        "deleted": 0,
        "taken": 0,
        "projects": 0,
    }


def test_both_answers_count_as_triaged_and_nothing_else_does(api: Fixture) -> None:
    """Discarded, or in a project. A favourite is not an answer any more."""
    kick, hat, loop = (api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3"))
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/files/{hat}/deleted")
    api.client.put(f"/api/projects/{project_id}/sounds/{loop}")

    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO favorite (hash, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
        (kick,),
    )
    conn.commit()
    conn.close()

    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 2
    assert body["untriaged"] == 1  # the starred one is still undecided
    assert (body["deleted"], body["taken"], body["projects"]) == (1, 1, 1)


def test_a_sound_answered_twice_is_still_one_sound_done(api: Fixture) -> None:
    """The two counts overlap on purpose. The total must not double-count."""
    kick = api.hash_of("kick.wav")
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    api.client.put(f"/api/files/{kick}/deleted")

    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 1
    assert body["untriaged"] == 2
    assert body["percent"] == 33.33
    assert (body["deleted"], body["taken"]) == (1, 1)


def test_undoing_a_decision_takes_it_off_the_counter(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/deleted")
    assert api.client.get("/api/triage").json()["triaged"] == 1
    api.client.delete(f"/api/files/{kick}/deleted")
    assert api.client.get("/api/triage").json()["triaged"] == 0


def test_taking_a_sound_out_of_a_project_untriages_it(api: Fixture) -> None:
    """Membership is the decision, so losing it is losing the decision."""
    kick = api.hash_of("kick.wav")
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{kick}")
    assert api.client.get("/api/triage").json()["triaged"] == 1
    api.client.delete(f"/api/projects/{project_id}/sounds/{kick}")
    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 0
    assert body["taken"] == 0


def test_a_project_written_by_hand_counts_too(api: Fixture) -> None:
    """The files are the truth, and the counter is read through them."""
    import json

    from audio_browser.projects import model

    document = model.new_document("by-hand", "by hand", model.utc_now())
    document["sounds"] = [
        {
            "hash": api.hash_of("kick.wav"),
            "added_at": model.utc_now(),
            "role": None,
            "note": "",
        }
    ]
    api.projects_dir.mkdir(parents=True, exist_ok=True)
    (api.projects_dir / "by-hand.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 1 and body["taken"] == 1


def test_a_bulk_pass_moves_the_counter(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 3
    assert body["percent"] == 100.0


# --------------------------------------------------------------------- swipe
#
# One sound at a time, two actions, no way to defer. Everything below is about
# the queue never handing back a sound that has already been answered.


def test_the_queue_hands_back_one_sound_and_what_the_view_needs(
    api: Fixture,
) -> None:
    """One request per sound, not three: the waveform and the player are fed."""
    kick = api.hash_of("kick.wav")
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO silence (hash, silent_s, duration_s, silent_frac, measured_at)"
        " VALUES (?, 0.5, 1.5, 0.33, '2026-09-17T00:00:00Z')",
        (kick,),
    )
    conn.execute(
        "INSERT INTO silence_interval (hash, start_s, end_s) VALUES (?, 0.0, 0.5)",
        (kick,),
    )
    conn.execute(
        "INSERT INTO span (hash, method, start_s, end_s, label, confidence, detail)"
        " VALUES (?, 'yamnet', 0.5, 1.5, 'music', 0.8, 'drum kit')",
        (kick,),
    )
    conn.commit()
    conn.close()

    body = api.client.get("/api/swipe").json()
    assert body["total"] == 3
    assert body["decided"] == 0
    assert body["remaining"] == 3
    assert body["sound"]["hash"] is not None

    # Whichever sound comes first, its own measurements come with it.
    if body["sound"]["hash"] == kick:
        assert body["silence"]["intervals"] == [{"start_s": 0.0, "end_s": 0.5}]
        assert [s["detail"] for s in body["spans"]["items"]] == ["drum kit"]
    assert body["silence"]["hash"] == body["sound"]["hash"]
    assert body["spans"]["method"] == "yamnet"


def test_the_queue_is_the_same_sound_until_that_sound_is_answered(
    api: Fixture,
) -> None:
    """A reload resumes. It does not reshuffle and it does not skip."""
    first = api.client.get("/api/swipe").json()["sound"]["hash"]
    assert api.client.get("/api/swipe").json()["sound"]["hash"] == first
    assert api.client.get("/api/swipe").json()["sound"]["hash"] == first


def test_a_discarded_sound_never_comes_round_again(api: Fixture) -> None:
    seen: list[str] = []
    for _ in range(3):
        digest = api.client.get("/api/swipe").json()["sound"]["hash"]
        seen.append(digest)
        api.client.put(f"/api/files/{digest}/deleted")

    assert len(set(seen)) == 3
    empty = api.client.get("/api/swipe").json()
    assert empty["sound"] is None and empty["remaining"] == 0
    assert empty["silence"] is None and empty["spans"] is None


def test_a_taken_sound_never_comes_round_again(api: Fixture) -> None:
    project_id = api.project_id("rust and rebar")
    first = api.client.get("/api/swipe").json()["sound"]["hash"]
    api.client.put(f"/api/projects/{project_id}/sounds/{first}")

    second = api.client.get("/api/swipe").json()
    assert second["sound"]["hash"] != first
    assert second["decided"] == 1 and second["remaining"] == 2


def test_the_queue_survives_a_reload_without_repeating_itself(
    api: Fixture,
) -> None:
    """A simulated reload: a fresh client over the same index, mid-pass.

    Nothing about the queue lives in the client, so what it answers after a
    reload is the queue as the index has it, with everything already answered
    left out.
    """
    from fastapi.testclient import TestClient

    from audio_browser.config import ProjectsConfig
    from audio_browser.server.app import create_app
    from conftest import schemas_dir

    project_id = api.project_id("rust and rebar")
    answered: list[str] = []
    first = api.client.get("/api/swipe").json()["sound"]["hash"]
    api.client.put(f"/api/projects/{project_id}/sounds/{first}")
    answered.append(first)
    second = api.client.get("/api/swipe").json()["sound"]["hash"]
    api.client.put(f"/api/files/{second}/deleted")
    answered.append(second)

    reloaded = create_app(
        api.db_path,
        projects=ProjectsConfig(dir=api.projects_dir, schemas_dir=schemas_dir()),
    )
    with TestClient(reloaded) as client:
        body = client.get("/api/swipe").json()
        assert body["sound"]["hash"] not in answered
        assert body["decided"] == 2 and body["remaining"] == 1
        # And the same sound again, because nothing has answered it yet.
        assert client.get("/api/swipe").json()["sound"]["hash"] == body["sound"]["hash"]


def test_the_queue_names_the_project_a_sound_would_go_into(api: Fixture) -> None:
    """One lane, so there is never a choice of project to make."""
    assert api.client.get("/api/swipe").json()["project"] is None

    project_id = api.project_id("rust and rebar")
    body = api.client.get("/api/swipe").json()
    assert body["project"]["id"] == project_id
    assert body["project"]["encumbered"] is False


def test_a_committed_project_is_not_offered_as_somewhere_to_take_a_sound(
    api: Fixture,
) -> None:
    """Its sound set is frozen, so the swipe view must not imply it can grow."""
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{api.hash_of('kick.wav')}")
    api.client.post(
        f"/api/projects/{project_id}/commit", json={"expect_column": "stored"}
    )
    assert api.client.get("/api/swipe").json()["project"] is None


def test_the_queue_is_a_read_and_answers_nothing_by_itself(api: Fixture) -> None:
    before = tree_snapshot(api.tmp_path / "source")
    api.client.get("/api/swipe")
    assert api.client.get("/api/triage").json()["triaged"] == 0
    assert count(api.db_path, "soft_delete") == 0
    assert tree_snapshot(api.tmp_path / "source") == before
