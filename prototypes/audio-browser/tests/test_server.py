from __future__ import annotations

import io
import shutil
import sqlite3
import subprocess
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_browser.config import Root
from audio_browser.db import open_db
from audio_browser.dedupe import record_deletion
from audio_browser.scan import scan_roots
from audio_browser.server.app import create_app
from conftest import Fixture, _quiet, needs_ffmpeg, peek, tree_snapshot, write_wav

# Every route that names a sound, with a placeholder for the hash. The traversal
# test walks all of them: the defence has to hold on each one, not just on one.
HASH_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/files/{h}"),
    ("GET", "/api/files/{h}/peaks"),
    ("GET", "/api/files/{h}/stream"),
    ("GET", "/api/files/{h}/spans"),
    ("GET", "/api/files/{h}/silence"),
    ("GET", "/api/files/{h}/slice?start=0&end=1"),
    ("PUT", "/api/files/{h}/deleted"),
    ("DELETE", "/api/files/{h}/deleted"),
)

# Values a hostile client might send in place of a hash. None of them is 64 hex
# characters, so none of them reaches SQL or the filesystem.
HOSTILE_HASHES: tuple[str, ...] = (
    "..",
    "../../etc/passwd",
    "..%2f..%2f..%2fetc%2fpasswd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/etc/passwd",
    "....//....//etc/passwd",
    "~/.ssh/id_rsa",
    "a" * 64 + "/../../etc/passwd",
    "' OR 1=1 --",
    "%00",
    "ZZZZ" + "a" * 60,  # right length, wrong alphabet
    "A" * 64,  # right length, uppercase
    "abc",
)


# ---------------------------------------------------------------- path safety


@pytest.mark.parametrize("method,template", HASH_ROUTES)
@pytest.mark.parametrize("hostile", HOSTILE_HASHES)
def test_a_hostile_hash_cannot_reach_the_filesystem(
    api: Fixture, method: str, template: str, hostile: str
) -> None:
    """No client-supplied value ever becomes a path.

    Anything that is not a blake3 digest is refused before a query runs, so the
    worst case is a 400 or a routing miss. Nothing is read, nothing escapes.
    """
    response = api.client.request(method, template.format(h=hostile))
    assert response.status_code in (400, 404, 405), response.text
    body = response.text
    assert "root:" not in body  # no /etc/passwd content came back
    assert "/etc/passwd" not in body


def test_an_absent_but_well_formed_hash_is_a_clean_404(api: Fixture) -> None:
    missing = "0" * 64
    for method, template in HASH_ROUTES:
        response = api.client.request(method, template.format(h=missing))
        assert response.status_code == 404
        assert response.json()["detail"] == "unknown hash"


def test_the_hash_error_names_the_rule(api: Fixture) -> None:
    response = api.client.get("/api/files/not-a-hash")
    assert response.status_code == 400
    assert "64" in response.json()["detail"]


# ---------------------------------------------------------------------- list


def test_health(api: Fixture) -> None:
    body = api.client.get("/api/health").json()
    assert body["ok"] is True
    assert body["blobs"] == 3
    assert body["aliases"] == 6


def test_list_has_one_row_per_sound_not_per_path(api: Fixture) -> None:
    body = api.client.get("/api/files").json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert {item["alias_count"] for item in body["items"]} == {2}


def test_list_sorts_by_name(api: Fixture) -> None:
    items = api.client.get("/api/files?sort=name&order=asc").json()["items"]
    assert [i["filename"] for i in items] == ["hat.wav", "kick.wav", "loop.mp3"]


def test_list_sorts_by_duration(api: Fixture) -> None:
    items = api.client.get("/api/files?sort=duration&order=desc").json()["items"]
    assert [i["duration_s"] for i in items] == [30.0, 1.5, 0.25]


def test_the_only_orders_left_are_ones_you_could_choose_a_sound_by(
    api: Fixture,
) -> None:
    """Name, running time, sounding time. Size and alias count are gone.

    Nobody picks a sound because it is large or because four paths reach it.
    Both were orders you could browse in without deciding anything.
    """
    for gone in ("size", "aliases"):
        assert api.client.get(f"/api/files?sort={gone}").status_code == 422
    for kept in ("name", "duration", "sounding"):
        assert api.client.get(f"/api/files?sort={kept}").status_code == 200


def test_list_filters_by_filename(api: Fixture) -> None:
    body = api.client.get("/api/files?q=kic").json()
    assert body["total"] == 1
    assert body["items"][0]["filename"] == "kick.wav"


def test_search_term_wildcards_are_literal(api: Fixture) -> None:
    assert api.client.get("/api/files?q=%25").json()["total"] == 0
    assert api.client.get("/api/files?q=_").json()["total"] == 0


def test_list_filters_by_extension(api: Fixture) -> None:
    assert api.client.get("/api/files?ext=mp3").json()["total"] == 1
    assert api.client.get("/api/files?ext=.WAV").json()["total"] == 2
    assert api.client.get("/api/files?ext=wav,mp3").json()["total"] == 3


def test_list_filters_by_duration(api: Fixture) -> None:
    assert api.client.get("/api/files?min_dur=1").json()["total"] == 2
    assert api.client.get("/api/files?max_dur=1").json()["total"] == 1
    assert api.client.get("/api/files?min_dur=1&max_dur=2").json()["total"] == 1


def test_list_pages(api: Fixture) -> None:
    first = api.client.get("/api/files?limit=2&offset=0").json()
    second = api.client.get("/api/files?limit=2&offset=2").json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    seen = {i["hash"] for i in first["items"]} | {i["hash"] for i in second["items"]}
    assert len(seen) == 3


def test_bad_sort_key_is_rejected(api: Fixture) -> None:
    assert api.client.get("/api/files?sort=path").status_code == 422
    assert api.client.get("/api/files?limit=0").status_code == 422
    assert api.client.get("/api/files?offset=-1").status_code == 422


# -------------------------------------------------------------------- detail


def test_detail_lists_every_alias(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    body = api.client.get(f"/api/files/{digest}").json()
    assert body["hash"] == digest
    assert body["alias_count"] == 2
    assert len(body["aliases"]) == 2
    assert {a["root"] for a in body["aliases"]} == {"source", "copy"}
    assert all(a["exists"] for a in body["aliases"])
    assert body["playable"] is True
    assert body["transcoded"] is False


def test_detail_reports_a_stale_alias(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    (api.tmp_path / "source" / "kick.wav").unlink()
    aliases = api.client.get(f"/api/files/{digest}").json()["aliases"]
    assert [a["exists"] for a in aliases] == [False, True]


def test_detail_has_no_deleted_sightings_by_default(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    assert api.client.get(f"/api/files/{digest}").json()["deleted_sightings"] == []


def test_detail_remembers_a_path_the_dedupe_removed(api: Fixture) -> None:
    """A removed path stays visible as history, not as a playable alias."""
    digest = api.hash_of("kick.wav")
    gone = str(api.tmp_path / "copy" / "kick.wav")
    conn = open_db(api.db_path)
    try:
        record_deletion(
            conn,
            file_hash=digest,
            path=gone,
            root="copy",
            reason="redundant copy; kept elsewhere",
            when="2026-02-03T04:05:06+00:00",
        )
        conn.commit()
    finally:
        conn.close()

    body = api.client.get(f"/api/files/{digest}").json()
    assert [a["path"] for a in body["aliases"]] == [
        str(api.tmp_path / "source" / "kick.wav")
    ]
    assert body["deleted_sightings"] == [
        {
            "path": gone,
            "root": "copy",
            "deleted_at": "2026-02-03T04:05:06+00:00",
            "reason": "redundant copy; kept elsewhere",
        }
    ]


# --------------------------------------------------------------------- peaks


@needs_ffmpeg
def test_peaks_are_computed_once_then_cached(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    assert peek(api.db_path, "SELECT peaks FROM blob WHERE hash = ?", digest)[
        "peaks"
    ] is None

    first = api.client.get(f"/api/files/{digest}/peaks").json()
    assert first["cached"] is False
    assert first["buckets"] == 1000
    assert len(first["peaks"]) == 1000
    assert any(lo != 0 or hi != 0 for lo, hi in first["peaks"])

    stored = peek(api.db_path, "SELECT peaks FROM blob WHERE hash = ?", digest)
    assert stored["peaks"] is not None
    assert len(stored["peaks"]) == 2000

    second = api.client.get(f"/api/files/{digest}/peaks").json()
    assert second["cached"] is True
    assert second["peaks"] == first["peaks"]


@needs_ffmpeg
def test_peaks_come_from_whichever_alias_survives(api: Fixture) -> None:
    digest = api.hash_of("hat.wav")
    (api.tmp_path / "source" / "hat.wav").unlink()
    assert api.client.get(f"/api/files/{digest}/peaks").status_code == 200


def test_peaks_of_a_vanished_sound_fail_cleanly(api: Fixture) -> None:
    digest = api.hash_of("hat.wav")
    (api.tmp_path / "source" / "hat.wav").unlink()
    (api.tmp_path / "copy" / "hat.wav").unlink()
    response = api.client.get(f"/api/files/{digest}/peaks")
    assert response.status_code == 422


# ------------------------------------------------------------------ streaming


def test_stream_sends_the_whole_file(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    expected = (api.tmp_path / "source" / "kick.wav").read_bytes()
    response = api.client.get(f"/api/files/{digest}/stream")
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["content-length"] == str(len(expected))
    assert response.content == expected


def test_stream_honours_a_range(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    expected = (api.tmp_path / "source" / "kick.wav").read_bytes()
    response = api.client.get(
        f"/api/files/{digest}/stream", headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{len(expected)}"
    assert response.headers["content-length"] == "100"
    assert response.content == expected[100:200]


def test_stream_honours_an_open_ended_range(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    expected = (api.tmp_path / "source" / "kick.wav").read_bytes()
    response = api.client.get(
        f"/api/files/{digest}/stream", headers={"Range": "bytes=44-"}
    )
    assert response.status_code == 206
    assert response.content == expected[44:]


def test_stream_rejects_a_range_past_the_end(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    size = (api.tmp_path / "source" / "kick.wav").stat().st_size
    response = api.client.get(
        f"/api/files/{digest}/stream", headers={"Range": f"bytes={size + 10}-"}
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{size}"


def test_head_reports_the_size_without_the_body(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    size = (api.tmp_path / "source" / "kick.wav").stat().st_size
    response = api.client.head(f"/api/files/{digest}/stream")
    assert response.status_code == 200
    assert response.headers["content-length"] == str(size)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == b""


def test_head_honours_a_range(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    size = (api.tmp_path / "source" / "kick.wav").stat().st_size
    response = api.client.head(
        f"/api/files/{digest}/stream", headers={"Range": "bytes=0-9"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-9/{size}"
    assert response.content == b""


def test_stream_sets_the_media_type_from_the_extension(api: Fixture) -> None:
    digest = api.hash_of("loop.mp3")
    response = api.client.get(f"/api/files/{digest}/stream")
    assert response.headers["content-type"].startswith("audio/mpeg")


def test_stream_falls_through_to_a_surviving_alias(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    expected = (api.tmp_path / "copy" / "kick.wav").read_bytes()
    (api.tmp_path / "source" / "kick.wav").unlink()
    response = api.client.get(f"/api/files/{digest}/stream")
    assert response.status_code == 200
    assert response.content == expected


def test_stream_404s_when_every_alias_is_gone(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    (api.tmp_path / "source" / "kick.wav").unlink()
    (api.tmp_path / "copy" / "kick.wav").unlink()
    response = api.client.get(f"/api/files/{digest}/stream")
    assert response.status_code == 404
    assert "on disk" in response.json()["detail"]


def test_stream_reads_a_write_protected_file(api: Fixture) -> None:
    """The real roots are chmod a-w. Streaming must not need write access."""
    digest = api.hash_of("hat.wav")
    for root in ("source", "copy"):
        (api.tmp_path / root / "hat.wav").chmod(0o444)
    assert api.client.get(f"/api/files/{digest}/stream").status_code == 200


@needs_ffmpeg
def test_aiff_is_transcoded_to_wav(tmp_path: Path) -> None:
    source = tmp_path / "aiffs"
    seed = write_wav(source / "seed.wav", freq=440, seconds=0.3)
    aiff = source / "pad.aif"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(seed), str(aiff)], check=True
    )
    seed.unlink()

    db_path = tmp_path / "aiff.db"
    conn = open_db(db_path)
    scan_roots(
        conn,
        [Root("aiffs", source.resolve())],
        workers=1,
        probe=False,
        log=_quiet,
    )
    digest = conn.execute("SELECT hash FROM alias LIMIT 1").fetchone()["hash"]
    conn.close()

    with TestClient(create_app(db_path)) as client:
        detail = client.get(f"/api/files/{digest}").json()
        assert detail["transcoded"] is True

        head = client.head(f"/api/files/{digest}/stream")
        assert head.status_code == 200
        assert head.headers["accept-ranges"] == "none"
        assert "content-length" not in head.headers
        assert head.content == b""

        response = client.get(f"/api/files/{digest}/stream")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        # Transcoded bodies have no known length, so they cannot be seeked.
        assert response.headers["accept-ranges"] == "none"
        assert response.headers["x-transcoded-from"] == ".aif"
        assert response.content[:4] == b"RIFF"
        assert response.content[8:12] == b"WAVE"
        assert len(response.content) > 1000


# ----------------------------------------------------------------- favorites
#
# There is no favourite route. A star meant "keep this, decide later", and the
# queue has two answers and no later.


def test_there_is_no_way_to_star_a_sound(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    for method in ("PUT", "DELETE"):
        response = api.client.request(method, f"/api/files/{digest}/favorite")
        assert response.status_code in (404, 405), response.text
    assert "/api/files/{file_hash}/favorite" not in {
        route.path
        for route in api.client.app.routes  # type: ignore[attr-defined]
    }


def test_the_favourite_rows_are_left_exactly_where_they_are(api: Fixture) -> None:
    """Removing the route was the decision. Dropping the data is not one.

    There is one favourite in the real index. The route it was set through is
    gone; the row it wrote is not, and nothing here is allowed to remove it.
    """
    digest = api.hash_of("kick.wav")
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO favorite (hash, created_at, note) VALUES (?, ?, ?)",
        (digest, "2026-01-01T00:00:00+00:00", "the one"),
    )
    conn.commit()
    conn.close()

    api.client.put(f"/api/files/{digest}/deleted")
    api.client.post("/api/bulk", json={"hashes": [digest], "action": "restore"})
    api.client.get("/api/files")
    api.client.get(f"/api/files/{digest}")

    row = peek(api.db_path, "SELECT note FROM favorite WHERE hash = ?", digest)
    assert row["note"] == "the one"


def test_a_sound_no_longer_reports_a_favourite_state(api: Fixture) -> None:
    """The field is gone from the list and the detail alike.

    A star drawn in a list is an offer to defer, and there is nothing behind it
    any more: no route sets it and no count uses it.
    """
    digest = api.hash_of("kick.wav")
    assert "favorite" not in api.client.get("/api/files").json()["items"][0]
    detail = api.client.get(f"/api/files/{digest}").json()
    assert "favorite" not in detail
    assert "favorite_note" not in detail
    assert "favorited_at" not in detail


# --------------------------------------------------------------------- lists


def test_there_are_no_list_routes(api: Fixture) -> None:
    """Project membership replaced them. A list that is not a project is a
    maybe-pile with no exit."""
    paths = {
        route.path
        for route in api.client.app.routes  # type: ignore[attr-defined]
    }
    assert not [path for path in paths if path.startswith("/api/lists")]
    assert api.client.get("/api/lists").status_code == 404
    assert api.client.post("/api/lists", json={"name": "x"}).status_code == 404


def test_the_list_tables_and_their_rows_survive_the_routes(api: Fixture) -> None:
    digest = api.hash_of("kick.wav")
    conn = sqlite3.connect(api.db_path)
    conn.execute("INSERT INTO list (id, name, created_at) VALUES (1, 'keep', ?)",
                 ("2026-01-01T00:00:00+00:00",))
    conn.execute(
        "INSERT INTO list_member (list_id, hash, position, added_at)"
        " VALUES (1, ?, 1, ?)",
        (digest, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    api.client.put(f"/api/files/{digest}/deleted")
    api.client.get("/api/triage")

    assert peek(api.db_path, "SELECT COUNT(*) AS n FROM list")["n"] == 1
    assert peek(api.db_path, "SELECT COUNT(*) AS n FROM list_member")["n"] == 1


def test_the_detail_view_names_the_projects_holding_a_sound(api: Fixture) -> None:
    """What replaced list membership: where a sound was taken to."""
    digest = api.hash_of("kick.wav")
    project_id = api.project_id("rust and rebar")
    api.client.put(f"/api/projects/{project_id}/sounds/{digest}")

    detail = api.client.get(f"/api/files/{digest}").json()
    assert [p["id"] for p in detail["projects"]] == [project_id]
    assert detail["projects"][0]["name"] == "rust and rebar"
    assert "lists" not in detail


# --------------------------------------------------------------------- dupes


def test_dupes_lists_every_multi_alias_hash(api: Fixture) -> None:
    body = api.client.get("/api/dupes?within_root=false").json()
    assert body["total"] == 3
    assert body["extra_copies"] == 3
    for group in body["items"]:
        assert group["copies"] == 2
        assert len(group["paths"]) == 2
        assert group["wasted_bytes"] == group["size_bytes"]
    assert body["wasted_bytes"] == sum(g["size_bytes"] for g in body["items"])


def test_dupes_ignores_a_pure_mirror_by_default(api: Fixture) -> None:
    """Two roots holding the same sounds are a working copy, not waste.

    Every blob in this fixture appears once per root and nowhere twice inside
    one root, so the default view has nothing to report. Without this scoping a
    mirrored library reports almost every sound as a duplicate.
    """
    body = api.client.get("/api/dupes").json()
    assert body["total"] == 0
    assert body["extra_copies"] == 0
    assert body["wasted_bytes"] == 0
    assert body["items"] == []


def test_dupes_pages(api: Fixture) -> None:
    body = api.client.get("/api/dupes?limit=1&offset=1&within_root=false").json()
    assert body["total"] == 3
    assert len(body["items"]) == 1


# ------------------------------------------------- dupes: project bundle guard


@pytest.fixture
def bundled(tmp_path: Path) -> Iterator[Fixture]:
    """One root holding two kinds of within-root duplicate.

    ``loose.wav`` sits twice in ordinary folders, so a cleanup could remove one.
    ``track.wav`` sits three times inside Logic project bundles, where the bytes
    belong to the project that reads them. Removing one of those corrupts that
    project, so it is redundancy that cannot be reclaimed.
    """
    root = tmp_path / "compost"
    write_wav(root / "samples" / "loose.wav", freq=300, seconds=0.5)
    write_wav(root / "packs" / "loose-copy.wav", freq=300, seconds=0.5)
    for n in (1, 2, 3):
        write_wav(
            root / f"song_{n}.logicx" / "Media" / "Audio Files" / "track.wav",
            freq=700,
            seconds=0.4,
        )

    db_path = tmp_path / "index.db"
    conn = open_db(db_path)
    scan_roots(
        conn, [Root("compost", root.resolve())], workers=2, probe=False, log=_quiet
    )
    hashes = {
        str(r["filename"]): str(r["hash"])
        for r in conn.execute("SELECT DISTINCT filename, hash FROM alias")
    }
    conn.close()

    with TestClient(create_app(db_path)) as client:
        yield Fixture(
            client=client, db_path=db_path, tmp_path=tmp_path, hashes=hashes
        )


def test_dupes_hides_copies_locked_inside_a_project_bundle(bundled: Fixture) -> None:
    """The cleanup view lists only what a cleanup could actually remove."""
    body = bundled.client.get("/api/dupes").json()
    assert body["include_bundles"] is False
    assert [g["filename"] for g in body["items"]] == ["loose.wav"]
    assert body["total"] == 1
    assert body["wasted_bytes"] == body["items"][0]["size_bytes"]


def test_dupes_reports_what_the_bundle_guard_left_out(bundled: Fixture) -> None:
    """Hidden is not silent. The totals say how much was withheld, and why."""
    body = bundled.client.get("/api/dupes").json()
    assert body["excluded_bundle_groups"] == 1
    track_size = peek(
        bundled.db_path,
        "SELECT size_bytes FROM blob WHERE hash = ?",
        bundled.hash_of("track.wav"),
    )["size_bytes"]
    assert body["excluded_bundle_bytes"] == 2 * track_size


def test_bundle_paths_are_marked_undeletable_when_asked_for(bundled: Fixture) -> None:
    body = bundled.client.get("/api/dupes?include_bundles=true").json()
    assert body["include_bundles"] is True
    group = next(g for g in body["items"] if g["filename"] == "track.wav")
    assert group["bundle_copies"] == 3
    assert [e["in_bundle"] for e in group["entries"]] == [True, True, True]
    assert not any(e["deletable"] for e in group["entries"])


def test_a_loose_copy_stays_deletable(bundled: Fixture) -> None:
    group = next(
        g
        for g in bundled.client.get("/api/dupes").json()["items"]
        if g["filename"] == "loose.wav"
    )
    assert group["bundle_copies"] == 0
    assert all(e["deletable"] for e in group["entries"])
    assert all(not e["in_bundle"] for e in group["entries"])


def test_the_raw_count_also_honours_the_bundle_guard(bundled: Fixture) -> None:
    """``within_root=false`` widens the scope; it does not unlock the bundles."""
    body = bundled.client.get("/api/dupes?within_root=false").json()
    assert [g["filename"] for g in body["items"]] == ["loose.wav"]
    assert body["excluded_bundle_groups"] == 1


def test_a_file_merely_named_like_a_bundle_is_not_protected(tmp_path: Path) -> None:
    """The guard looks at directories, not at names that happen to contain one."""
    root = tmp_path / "root"
    write_wav(root / "a" / "mix.logicx.wav", freq=90, seconds=0.3)
    write_wav(root / "b" / "mix.logicx.wav", freq=90, seconds=0.3)
    db_path = tmp_path / "index.db"
    conn = open_db(db_path)
    scan_roots(
        conn, [Root("root", root.resolve())], workers=1, probe=False, log=_quiet
    )
    conn.close()
    with TestClient(create_app(db_path)) as client:
        body = client.get("/api/dupes").json()
    assert body["total"] == 1
    assert body["items"][0]["bundle_copies"] == 0


# Every DELETE the server answers, and what each one removes. Not one of them
# is a file. A new entry here has to be justified in this list before the test
# will pass, which is the point: adding a DELETE route is a decision, not a
# detail.
ALLOWED_DELETES: dict[str, str] = {
    "/api/files/{file_hash}/deleted": "a row in `soft_delete`, which restores a sound",
    "/api/projects/{project_id}/sounds/{file_hash}": (
        "one entry from a project document's `sounds` array. The sound stays in "
        "the library and in every other project, and every path that held its "
        "bytes still holds them."
    ),
}


def test_no_route_can_remove_an_audio_file(api: Fixture) -> None:
    """The dupes view is for seeing redundancy. Removal is done by ear, by hand.

    Every DELETE the server accepts removes a row about a sound. None removes a
    sound, and none removes a file. If a route that deletes a path is ever
    added, this test is where it shows up.
    """
    deletes = sorted(
        route.path
        for route in api.client.app.routes  # type: ignore[attr-defined]
        if "DELETE" in (getattr(route, "methods", None) or set())
    )
    assert deletes == sorted(ALLOWED_DELETES)


# Every route that changes state, with the body it needs. The filesystem test
# below drives all of them in turn. Soft delete is the one that most looks like
# it should touch a file, so it is exercised twice: discard, then restore.
def _mutations(
    file_hash: str, other_hash: str, project_id: str, second_project: str
) -> list[tuple[str, str, object]]:
    return [
        ("PUT", f"/api/files/{file_hash}/deleted", {"note": "not this one"}),
        ("DELETE", f"/api/files/{file_hash}/deleted", None),
        ("POST", "/api/bulk", {"hashes": [file_hash, other_hash], "action": "delete"}),
        ("POST", "/api/bulk", {"hashes": [file_hash, other_hash], "action": "restore"}),
        # Every project route, in an order that reaches all of them. The first
        # project is driven as far down the board as the board goes: sounds in
        # and out, abandoned, revived, committed out of `stored`, cut, then
        # committed out of `collage` into `enrich`. The second is only
        # abandoned, so the abandon route is exercised against a project that
        # never holds a sound.
        ("PATCH", f"/api/projects/{project_id}", {"name": "renamed", "notes": "x"}),
        ("PUT", f"/api/projects/{project_id}/sounds/{file_hash}", None),
        ("PUT", f"/api/projects/{project_id}/sounds/{other_hash}", None),
        ("DELETE", f"/api/projects/{project_id}/sounds/{other_hash}", None),
        ("POST", f"/api/projects/{project_id}/abandon", {"reason": "not yet"}),
        ("POST", f"/api/projects/{project_id}/revive", {"override": True}),
        ("POST", f"/api/projects/{project_id}/commit", {"expect_column": "stored"}),
        (
            "PUT",
            f"/api/projects/{project_id}/collage",
            {
                "regions": [
                    {
                        "id": "r1",
                        "hash": file_hash,
                        "track": 0,
                        "start_s": 0.1,
                        "end_s": 0.4,
                        "at_s": 0.0,
                    }
                ]
            },
        ),
        ("POST", f"/api/projects/{project_id}/commit", {"expect_column": "collage"}),
        ("POST", f"/api/projects/{second_project}/abandon", None),
    ]


def test_every_mutating_route_leaves_every_file_on_disk(api: Fixture) -> None:
    """The route list is one half of the promise. This is the other half.

    Reading the source proves nothing if a helper three calls down opens a file
    for writing. So every state-changing route is actually driven, and the two
    audio roots are compared byte-count for byte-count before and after. A
    removal, a truncation or a rewrite all fail this.
    """
    before = {
        root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")
    }
    made = api.client.post("/api/projects", json={"name": "rust and rebar"})
    assert made.status_code == 201, made.text
    # `stored` holds one lane, so the second project is deliberate.
    second = api.client.post(
        "/api/projects", json={"name": "cold open", "override": True}
    )
    assert second.status_code == 201, second.text

    for method, path, body in _mutations(
        api.hash_of("kick.wav"),
        api.hash_of("hat.wav"),
        made.json()["id"],
        second.json()["id"],
    ):
        response = api.client.request(method, path, json=body)
        assert response.status_code < 400, f"{method} {path}: {response.text}"

    after = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    assert after == before


def test_the_swipe_queue_changes_nothing_at_all(api: Fixture) -> None:
    """It is a read. Answering happens through discard and project membership."""
    before = {
        root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")
    }
    counts = {
        table: peek(api.db_path, f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("blob", "alias", "soft_delete", "favorite", "list_member")
    }
    for _ in range(3):
        assert api.client.get("/api/swipe").status_code == 200
    after = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    assert after == before
    assert counts == {
        table: peek(api.db_path, f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("blob", "alias", "soft_delete", "favorite", "list_member")
    }


# --------------------------------------------------------------------- slice
#
# A region is cut from a source that can be hundreds of megabytes, so the whole
# file is never sent. The slice comes back in one format whatever the source
# was, and the source is only ever read.


def _slice(api: Fixture, name: str, start: float, end: float):  # type: ignore[no-untyped-def]
    return api.client.get(
        f"/api/files/{api.hash_of(name)}/slice", params={"start": start, "end": end}
    )


@needs_ffmpeg
def test_a_slice_is_48k_stereo_16_bit_whatever_the_source_was(api: Fixture) -> None:
    """The fixture sound is 8 kHz mono. The slice is not."""
    response = _slice(api, "kick.wav", 0.1, 0.3)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert int(response.headers["content-length"]) == len(response.content)

    with wave.open(io.BytesIO(response.content), "rb") as reader:
        assert reader.getframerate() == 48_000
        assert reader.getnchannels() == 2
        assert reader.getsampwidth() == 2
        # 0.2 s at 48 kHz. The resampler may land a frame either side.
        assert abs(reader.getnframes() - 9_600) <= 2


@needs_ffmpeg
def test_a_slice_is_the_span_asked_for_and_not_the_whole_sound(api: Fixture) -> None:
    short = _slice(api, "kick.wav", 0.0, 0.1).content
    long = _slice(api, "kick.wav", 0.0, 0.4).content
    with wave.open(io.BytesIO(short), "rb") as a, wave.open(io.BytesIO(long), "rb") as b:
        assert abs(b.getnframes() - 4 * a.getnframes()) <= 8


def test_a_slice_longer_than_the_cap_is_refused(api: Fixture) -> None:
    response = _slice(api, "kick.wav", 0.0, 120.5)
    assert response.status_code == 422
    assert "120" in response.json()["detail"]


def test_a_slice_that_ends_before_it_starts_is_refused(api: Fixture) -> None:
    assert _slice(api, "kick.wav", 0.3, 0.3).status_code == 422
    assert _slice(api, "kick.wav", 0.3, 0.1).status_code == 422
    assert _slice(api, "kick.wav", -1.0, 0.1).status_code == 422


@needs_ffmpeg
def test_a_slice_past_the_end_of_the_sound_is_refused(api: Fixture) -> None:
    """kick.wav is half a second long. No samples is an error, not a WAV."""
    response = _slice(api, "kick.wav", 5.0, 6.0)
    assert response.status_code == 422


def test_a_slice_of_an_unknown_hash_is_a_404(api: Fixture) -> None:
    response = api.client.get(f"/api/files/{'c' * 64}/slice?start=0&end=1")
    assert response.status_code == 404


@needs_ffmpeg
def test_a_slice_leaves_every_file_on_disk_as_it_was(api: Fixture) -> None:
    """The one route that opens audio for a project view. It only reads."""
    before = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    for name in ("kick.wav", "hat.wav", "loop.mp3"):
        assert _slice(api, name, 0.0, 0.1).status_code == 200
    after = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    assert after == before


# --------------------------------------------------------------------- spans


def test_spans_of_an_unclassified_sound_are_an_empty_list(api: Fixture) -> None:
    """Stage 2 writes no spans, so the route answers 200 with nothing in it.

    An empty list and a 404 read the same to a careless client. They are not the
    same: this says the sound exists and has no labels yet.
    """
    body = api.client.get(f"/api/files/{api.hash_of('kick.wav')}/spans").json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["hash"] == api.hash_of("kick.wav")


def test_spans_of_an_unknown_hash_are_a_404(api: Fixture) -> None:
    response = api.client.get(f"/api/files/{'b' * 64}/spans")
    assert response.status_code == 404


def test_spans_come_back_in_time_order(api: Fixture) -> None:
    file_hash = api.hash_of("kick.wav")
    conn = sqlite3.connect(api.db_path)
    conn.executemany(
        "INSERT INTO span (hash, method, start_s, end_s, label, confidence, detail)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (file_hash, "yamnet", 0.8, 1.5, "music", 0.7, "drum kit"),
            (file_hash, "yamnet", 0.0, 0.8, "speech", 0.9, None),
        ],
    )
    conn.commit()
    conn.close()

    body = api.client.get(f"/api/files/{file_hash}/spans").json()
    assert [s["start_s"] for s in body["items"]] == [0.0, 0.8]
    assert body["items"][0]["label"] == "speech"
    assert body["items"][1]["detail"] == "drum kit"


def test_spans_narrow_to_one_method(api: Fixture) -> None:
    """Methods are compared side by side, so each must be selectable alone."""
    file_hash = api.hash_of('hat.wav')
    conn = sqlite3.connect(api.db_path)
    conn.executemany(
        "INSERT INTO span (hash, method, start_s, end_s, label, confidence, detail)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (file_hash, "yamnet", 0.0, 0.2, "other", None, None),
            (file_hash, "clap", 0.0, 0.2, "music", None, None),
        ],
    )
    conn.commit()
    conn.close()

    body = api.client.get(f"/api/files/{file_hash}/spans?method=clap").json()
    assert body["method"] == "clap"
    assert [s["method"] for s in body["items"]] == ["clap"]


def test_the_span_table_is_created_on_an_older_index(tmp_path: Path) -> None:
    """An index written before stage 3 existed picks the table up on open."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE blob (hash TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL,"
        " duration_s REAL, sample_rate INTEGER, channels INTEGER, codec TEXT,"
        " peaks BLOB, probed_at TEXT)"
    )
    conn.execute("INSERT INTO blob (hash, size_bytes) VALUES (?, 10)", ("c" * 64,))
    conn.commit()
    conn.close()

    with TestClient(create_app(db_path)) as client:
        assert client.get(f"/api/files/{'c' * 64}/spans").json()["items"] == []


# --------------------------------------------- transcoded streams cannot seek


def test_the_list_says_which_sounds_cannot_be_seeked(tmp_path: Path) -> None:
    """AIFF is re-encoded on the way out, so its stream has no byte offsets.

    The flag rides on every list row because the player bar is fed from them,
    and a seek that silently does nothing is worse than one the interface
    refuses.
    """
    root = tmp_path / "root"
    write_wav(root / "native.wav", freq=200, seconds=0.3)
    # WAV bytes under an .aif name. The server keys on the extension, so this
    # exercises the flag without needing an encoder.
    write_wav(root / "recorded.aif", freq=210, seconds=0.3)
    db_path = tmp_path / "index.db"
    conn = open_db(db_path)
    scan_roots(
        conn, [Root("root", root.resolve())], workers=1, probe=False, log=_quiet
    )
    conn.close()

    with TestClient(create_app(db_path)) as client:
        rows = {
            r["filename"]: r for r in client.get("/api/files").json()["items"]
        }
        assert rows["native.wav"]["transcoded"] is False
        assert rows["recorded.aif"]["transcoded"] is True

        detail = client.get(f"/api/files/{rows['recorded.aif']['hash']}").json()
        assert detail["transcoded"] is True
        head = client.head(f"/api/files/{rows['recorded.aif']['hash']}/stream")
        assert head.headers["accept-ranges"] == "none"


# --------------------------------------------------------------------- stats


def test_stats_counts_the_collection(api: Fixture) -> None:
    body = api.client.get("/api/stats").json()
    assert body["blobs"] == 3
    assert body["aliases"] == 6
    assert body["duplicate_blobs"] == 3
    assert body["extra_copies"] == 3
    assert body["wasted_bytes"] == body["logical_bytes"]
    assert body["favorites"] == 0
    assert {e["name"] for e in body["extensions"]} == {".wav", ".mp3"}
    assert {r["root"] for r in body["roots"]} == {"source", "copy"}
    assert body["total_duration_s"] == pytest.approx(31.75)


def test_stats_still_counts_the_favourite_rows_that_are_left(api: Fixture) -> None:
    """The count is how the index says the rows survived the route's removal."""
    conn = sqlite3.connect(api.db_path)
    conn.execute(
        "INSERT INTO favorite (hash, created_at) VALUES (?, ?)",
        (api.hash_of("kick.wav"), "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    assert api.client.get("/api/stats").json()["favorites"] == 1


# ----------------------------------------------------------------------- cors


def test_cors_allows_the_frontend_origin(api: Fixture) -> None:
    response = api.client.get(
        "/api/files", headers={"Origin": "http://localhost:3100"}
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"


def test_cors_preflight_allows_a_discard_put(api: Fixture) -> None:
    response = api.client.options(
        f"/api/files/{api.hash_of('kick.wav')}/deleted",
        headers={
            "Origin": "http://localhost:3100",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_cors_rejects_an_unrelated_origin(api: Fixture) -> None:
    response = api.client.get(
        "/api/files", headers={"Origin": "http://evil.example.com"}
    )
    assert "access-control-allow-origin" not in response.headers


# ------------------------------------------------------------------- startup


def test_a_missing_database_is_refused(tmp_path: Path) -> None:
    from audio_browser.server.database import MissingDatabase

    with pytest.raises(MissingDatabase):
        create_app(tmp_path / "nope.db")
