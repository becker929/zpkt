"""The shared shell files at /app/shell/: one flat folder, the right types, no way out of it, the Host check first."""

from __future__ import annotations

import http.client

import pytest

from zpkt.app import web


def fetch(rig, path: str, host: str | None = None) -> tuple[int, str, bytes]:
    """One GET of exactly this path (http.client does not tidy `..` away, as urllib and a browser would)."""
    port = int(rig.url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
        r = conn.getresponse()
        return r.status, r.getheader("Content-Type", ""), r.read()
    finally:
        conn.close()


def test_the_stylesheet_and_the_tab_bar_are_served_with_their_types(rig):
    code, ctype, css = fetch(rig, "/app/shell/shell.css")
    assert code == 200 and ctype.startswith("text/css")
    assert b"--acc:#c6f432" in css and b"#tabs" in css
    code, ctype, js = fetch(rig, "/app/shell/nav.js")
    assert code == 200 and ctype.startswith("text/javascript")
    assert b"/app/ask/" in js


def test_the_shell_page_uses_them(rig):
    page = rig.get("/app/")[1]
    assert b'href="/app/shell/shell.css"' in page and b'src="/app/shell/nav.js"' in page
    assert b'<nav id="tabs" data-current="desk">' in page
    assert b'<span id="listen"></span>' in page and b'src="/app/shell/listen.js"' in page
    assert b'id="sask"' not in page  # Ask is a tab, not a stray button


@pytest.mark.parametrize(
    "path",
    [
        "/app/shell/",
        "/app/shell/missing.js",
        "/app/shell/../app.html",
        "/app/shell/..%2Fapp.html",
        "/app/shell/%2e%2e/app.html",
        "/app/shell/../../web.py",
        "/app/shell/sub/nav.js",
        "/app/shell//etc/passwd",
        "/app/shell/.hidden.js",
        "/app/shell/nav.js%00.css",
    ],
)
def test_nothing_outside_the_folder_is_served(rig, path):
    code, _, body = fetch(rig, path)
    assert code == 404 and b"<html" not in body


def test_a_file_of_another_type_in_the_folder_is_not_served(rig, tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("private")
    (tmp_path / "ok.css").write_text("a{}")
    (tmp_path / "link.css").symlink_to(tmp_path / "notes.txt")
    monkeypatch.setattr(web, "SHARED_DIR", tmp_path)
    assert fetch(rig, "/app/shell/ok.css")[0] == 200
    assert fetch(rig, "/app/shell/notes.txt")[0] == 404
    assert fetch(rig, "/app/shell/link.css")[0] == 404


def test_another_host_name_is_turned_away(rig):
    assert fetch(rig, "/app/shell/shell.css", host="evil.example")[0] == 403
