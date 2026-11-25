"""A page on another site may not write to the desk: its Origin names another host than the one asked."""

import urllib.error
import urllib.request

import pytest

from zpkt.app.web import cross_site


@pytest.mark.parametrize(
    ("origin", "host", "expected"),
    [
        (None, "127.0.0.1:8985", False),  # curl, the CLI, the tests
        ("", "127.0.0.1:8985", False),
        ("http://127.0.0.1:8985", "127.0.0.1:8985", False),  # the desk's own page
        ("https://studio.tail1234.ts.net", "studio.tail1234.ts.net", False),  # the tailnet name, same on both
        ("https://evil.example", "127.0.0.1:8985", True),
        ("http://127.0.0.1:9999", "127.0.0.1:8985", True),  # another local server
        ("null", "127.0.0.1:8985", True),
    ],
)
def test_cross_site(origin, host, expected):
    assert cross_site(origin, host) is expected


def send(rig, method, path, origin):
    req = urllib.request.Request(rig.url + path, data=b"{}", method=method, headers={"Origin": origin})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_a_write_from_another_site_is_refused_and_one_from_the_desks_own_page_is_not(rig):
    before = rig.get("/api/commands")[0]
    assert before == 200
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert send(rig, method, "/api/command", "https://evil.example") == 403, method
    assert send(rig, "POST", "/api/command", rig.url) == 400  # its own origin gets through to the handler (no kind)


def post_raw(rig, path, headers=None, data=b"{}"):
    req = urllib.request.Request(rig.url + path, data=data, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_a_write_with_no_origin_needs_a_token(rig, tmp_path, monkeypatch):
    from zpkt.app import token

    monkeypatch.setenv("ZPKT_CONFIG_DIR", str(tmp_path / "config"))
    assert post_raw(rig, "/api/command") == 401  # curl, a script: no page, no token
    assert post_raw(rig, "/api/command", {"Authorization": "Bearer nope"}) == 401
    good = token.ensure_token(None, "cli")
    assert post_raw(rig, "/api/command", {"Authorization": f"Bearer {good}"}) == 400  # in: no kind
    assert post_raw(rig, "/api/command", {"Origin": rig.url}) == 400  # the desk's own page


def test_a_bad_content_length_is_400_and_a_huge_one_413(rig):
    from zpkt.app import web

    assert post_raw(rig, "/api/command", {"Origin": rig.url, "Content-Length": "abc"}) == 400
    assert post_raw(rig, "/api/command", {"Origin": rig.url, "Content-Length": "-5"}) == 400
    assert post_raw(rig, "/api/command", {"Origin": rig.url, "Content-Length": str(web.MAX_BODY + 1)}) == 413
