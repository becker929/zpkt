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


def make_list(api: Fixture, name: str) -> int:
    response = api.client.post("/api/lists", json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


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


# --------------------------------------------------------------------- lists


def test_a_new_list_starts_empty(api: Fixture) -> None:
    body = api.client.post("/api/lists", json={"name": "Kicks"}).json()
    assert body["name"] == "Kicks"
    assert body["member_count"] == 0
    assert body["duration_s"] == 0
    assert body["size_bytes"] == 0


def test_two_lists_cannot_share_a_name(api: Fixture) -> None:
    make_list(api, "Kicks")
    clash = api.client.post("/api/lists", json={"name": "Kicks"})
    assert clash.status_code == 409
    assert "already exists" in clash.json()["detail"]


def test_a_list_name_is_trimmed_and_cannot_be_blank(api: Fixture) -> None:
    body = api.client.post("/api/lists", json={"name": "  Hats  "}).json()
    assert body["name"] == "Hats"
    assert api.client.post("/api/lists", json={"name": "   "}).status_code == 400
    assert api.client.post("/api/lists", json={"name": ""}).status_code == 422


def test_members_come_back_in_the_order_they_were_added(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    for name in ("loop.mp3", "kick.wav", "hat.wav"):
        response = api.client.put(
            f"/api/lists/{list_id}/members/{api.hash_of(name)}"
        )
        assert response.status_code == 200, response.text

    detail = api.client.get(f"/api/lists/{list_id}").json()
    assert [item["filename"] for item in detail["items"]] == [
        "loop.mp3",
        "kick.wav",
        "hat.wav",
    ]
    assert detail["member_count"] == 3
    assert detail["duration_s"] == pytest.approx(30.0 + 1.5 + 0.25)


def test_adding_a_sound_twice_keeps_its_place(api: Fixture) -> None:
    """A double-tap must not shuffle the queue someone is listening to."""
    list_id = make_list(api, "Session")
    first = api.client.put(
        f"/api/lists/{list_id}/members/{api.hash_of('kick.wav')}"
    ).json()
    api.client.put(f"/api/lists/{list_id}/members/{api.hash_of('hat.wav')}")
    again = api.client.put(
        f"/api/lists/{list_id}/members/{api.hash_of('kick.wav')}"
    ).json()
    assert again["position"] == first["position"]
    assert again["member_count"] == 2


def test_removing_a_member_leaves_the_sound_alone(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/lists/{list_id}/members/{kick}")
    before = tree_snapshot(api.tmp_path / "source")

    gone = api.client.delete(f"/api/lists/{list_id}/members/{kick}").json()
    assert gone["member"] is False
    assert gone["member_count"] == 0
    assert tree_snapshot(api.tmp_path / "source") == before
    assert api.client.get(f"/api/files/{kick}").status_code == 200


def test_the_detail_view_names_every_list_a_sound_is_in(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    for name in ("Kicks", "Session"):
        api.client.put(f"/api/lists/{make_list(api, name)}/members/{kick}")
    detail = api.client.get(f"/api/files/{kick}").json()
    assert [entry["name"] for entry in detail["lists"]] == ["Kicks", "Session"]


def test_renaming_a_list(api: Fixture) -> None:
    list_id = make_list(api, "Kicks")
    renamed = api.client.patch(f"/api/lists/{list_id}", json={"name": "Hard kicks"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Hard kicks"
    assert api.client.get("/api/lists").json()["items"][0]["name"] == "Hard kicks"


def test_renaming_onto_a_taken_name_is_a_conflict(api: Fixture) -> None:
    make_list(api, "Kicks")
    other = make_list(api, "Hats")
    clash = api.client.patch(f"/api/lists/{other}", json={"name": "Kicks"})
    assert clash.status_code == 409
    assert api.client.get(f"/api/lists/{other}").json()["name"] == "Hats"


def test_deleting_a_list_drops_its_members_and_nothing_else(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    for name in ("kick.wav", "hat.wav"):
        api.client.put(f"/api/lists/{list_id}/members/{api.hash_of(name)}")
    before = tree_snapshot(api.tmp_path / "source")

    removed = api.client.delete(f"/api/lists/{list_id}").json()
    assert removed == {"id": list_id, "name": "Session", "removed_members": 2}
    assert count(api.db_path, "list_member") == 0
    assert count(api.db_path, "blob") == 3
    assert tree_snapshot(api.tmp_path / "source") == before


def test_unknown_lists_are_404s_everywhere(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    for method, path in (
        ("GET", "/api/lists/999"),
        ("PATCH", "/api/lists/999"),
        ("DELETE", "/api/lists/999"),
        ("PUT", f"/api/lists/999/members/{kick}"),
        ("DELETE", f"/api/lists/999/members/{kick}"),
    ):
        response = api.client.request(method, path, json={"name": "x"})
        assert response.status_code == 404, f"{method} {path}"
        assert response.json()["detail"] == "unknown list"


def test_a_list_member_must_be_a_real_sound(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    assert (
        api.client.put(f"/api/lists/{list_id}/members/{'0' * 64}").status_code == 404
    )


def test_a_list_member_hash_is_checked_like_any_other(api: Fixture) -> None:
    """The gate on the hash is the same one every route uses."""
    list_id = make_list(api, "Session")
    response = api.client.put(f"/api/lists/{list_id}/members/../../etc/passwd")
    assert response.status_code in (400, 404, 405)
    assert "/etc/passwd" not in response.text


def test_a_list_page_can_be_walked(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    for name in ("loop.mp3", "kick.wav", "hat.wav"):
        api.client.put(f"/api/lists/{list_id}/members/{api.hash_of(name)}")
    page = api.client.get(f"/api/lists/{list_id}?limit=2&offset=1").json()
    assert page["member_count"] == 3  # the whole list, not the page
    assert [item["filename"] for item in page["items"]] == ["kick.wav", "hat.wav"]


# ---------------------------------------------------------------------- bulk


def test_bulk_star_reports_what_it_changed(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    api.client.put(f"/api/files/{hashes[0]}/favorite")  # already starred

    body = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "star"}
    ).json()
    assert body["requested"] == 3
    assert body["matched"] == 3
    assert body["changed"] == 2
    assert body["unchanged"] == 1
    assert body["skipped"] == 0
    assert count(api.db_path, "favorite") == 3


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
        "/api/bulk", json={"hashes": [kick, kick, kick], "action": "star"}
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


def test_bulk_add_to_list_keeps_the_order_it_was_sent(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    order = ["loop.mp3", "hat.wav", "kick.wav"]
    api.client.post(
        "/api/bulk",
        json={
            "hashes": [api.hash_of(n) for n in order],
            "action": "add_to_list",
            "list_id": list_id,
        },
    )
    detail = api.client.get(f"/api/lists/{list_id}").json()
    assert [item["filename"] for item in detail["items"]] == order


def test_bulk_add_to_list_appends_after_what_is_already_there(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    api.client.put(f"/api/lists/{list_id}/members/{api.hash_of('kick.wav')}")
    body = api.client.post(
        "/api/bulk",
        json={
            "hashes": [api.hash_of(n) for n in ("hat.wav", "kick.wav")],
            "action": "add_to_list",
            "list_id": list_id,
        },
    ).json()
    assert body["changed"] == 1  # kick was already a member
    detail = api.client.get(f"/api/lists/{list_id}").json()
    assert [item["filename"] for item in detail["items"]] == ["kick.wav", "hat.wav"]


def test_bulk_remove_from_list(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav")]
    api.client.post(
        "/api/bulk",
        json={"hashes": hashes, "action": "add_to_list", "list_id": list_id},
    )
    body = api.client.post(
        "/api/bulk",
        json={"hashes": hashes, "action": "remove_from_list", "list_id": list_id},
    ).json()
    assert body["changed"] == 2
    assert api.client.get(f"/api/lists/{list_id}").json()["member_count"] == 0


def test_a_list_action_without_a_list_is_refused(api: Fixture) -> None:
    response = api.client.post(
        "/api/bulk",
        json={"hashes": [api.hash_of("kick.wav")], "action": "add_to_list"},
    )
    assert response.status_code == 400
    assert "list_id" in response.json()["detail"]


def test_a_list_action_on_an_unknown_list_is_a_404(api: Fixture) -> None:
    response = api.client.post(
        "/api/bulk",
        json={
            "hashes": [api.hash_of("kick.wav")],
            "action": "add_to_list",
            "list_id": 999,
        },
    )
    assert response.status_code == 404


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
        "/api/bulk", json={"hashes": too_many, "action": "star"}
    )
    assert response.status_code == 422


def test_an_empty_batch_does_nothing_quietly(api: Fixture) -> None:
    body = api.client.post("/api/bulk", json={"hashes": [], "action": "star"}).json()
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
        "CREATE TRIGGER refuse_one BEFORE INSERT ON favorite "
        f"WHEN new.hash = '{hashes[1]}' "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    conn.commit()
    conn.close()

    try:
        with pytest.raises(sqlite3.IntegrityError):
            api.client.post("/api/bulk", json={"hashes": hashes, "action": "star"})
    finally:
        conn = sqlite3.connect(api.db_path)
        conn.execute("DROP TRIGGER refuse_one")
        conn.commit()
        conn.close()

    assert count(api.db_path, "favorite") == 0

    # The connection is usable again once the batch has rolled back.
    body = api.client.post(
        "/api/bulk", json={"hashes": hashes, "action": "star"}
    ).json()
    assert body["changed"] == 3


def test_a_bulk_action_never_touches_the_filesystem(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    before = {r: tree_snapshot(api.tmp_path / r) for r in ("source", "copy")}
    api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    after = {r: tree_snapshot(api.tmp_path / r) for r in ("source", "copy")}
    assert after == before


# -------------------------------------------------------------------- triage


def test_nothing_decided_is_nothing_triaged(api: Fixture) -> None:
    body = api.client.get("/api/triage").json()
    assert body == {
        "total": 3,
        "triaged": 0,
        "untriaged": 3,
        "percent": 0.0,
        "starred": 0,
        "deleted": 0,
        "listed": 0,
        "lists": 0,
    }


def test_each_of_the_three_states_counts_as_triaged(api: Fixture) -> None:
    kick, hat, loop = (api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3"))
    api.client.put(f"/api/files/{kick}/favorite")
    api.client.put(f"/api/files/{hat}/deleted")
    api.client.put(f"/api/lists/{make_list(api, 'Session')}/members/{loop}")

    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 3
    assert body["untriaged"] == 0
    assert body["percent"] == 100.0
    assert (body["starred"], body["deleted"], body["listed"]) == (1, 1, 1)
    assert body["lists"] == 1


def test_a_sound_decided_three_ways_is_still_one_sound_done(api: Fixture) -> None:
    """The split overlaps on purpose. The total must not double-count."""
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/favorite")
    api.client.put(f"/api/files/{kick}/deleted")
    api.client.put(f"/api/lists/{make_list(api, 'Session')}/members/{kick}")

    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 1
    assert body["untriaged"] == 2
    assert body["percent"] == 33.33
    assert (body["starred"], body["deleted"], body["listed"]) == (1, 1, 1)


def test_undoing_a_decision_takes_it_off_the_counter(api: Fixture) -> None:
    kick = api.hash_of("kick.wav")
    api.client.put(f"/api/files/{kick}/deleted")
    assert api.client.get("/api/triage").json()["triaged"] == 1
    api.client.delete(f"/api/files/{kick}/deleted")
    assert api.client.get("/api/triage").json()["triaged"] == 0


def test_deleting_a_list_untriages_what_only_that_list_held(api: Fixture) -> None:
    list_id = make_list(api, "Session")
    api.client.put(f"/api/lists/{list_id}/members/{api.hash_of('kick.wav')}")
    assert api.client.get("/api/triage").json()["triaged"] == 1
    api.client.delete(f"/api/lists/{list_id}")
    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 0
    assert body["lists"] == 0


def test_a_bulk_pass_moves_the_counter(api: Fixture) -> None:
    hashes = [api.hash_of(n) for n in ("kick.wav", "hat.wav", "loop.mp3")]
    api.client.post("/api/bulk", json={"hashes": hashes, "action": "delete"})
    body = api.client.get("/api/triage").json()
    assert body["triaged"] == 3
    assert body["percent"] == 100.0
