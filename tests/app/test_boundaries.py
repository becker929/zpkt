"""The architecture, checked on the source: zpkt.live and zpkt.audio are libraries that never open a connection.

Only zpkt.app opens connections, and hands them in. A static AST check, so a module that sneaks one in fails here.
Allowed: the CLI modules (`*_cli.py`, `cli.py`, `cli_options.py`), the fakes in testing/, and transport.py (it is the
LiveClient itself).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "zpkt"
LIBRARIES = ("live", "audio")

# Files in the libraries that may open a connection, with the reason.
ALLOWED = {
    "live/transport.py": "it is the LiveClient: the one place a connection to Live is made",
    "live/cli.py": "the `zpkt live` command line",
    "live/cli_options.py": "the command line's options",
    "audio/cli.py": "the `zpkt audio` command line",
    "live/rig.py": "setup and doctor stay direct: the rig check and reset build a client when none is given",
}
# Known debt, listed so it cannot grow: file -> how many places still build a LiveClient. Each becomes an app client.
DEBT = {"live/session.py": 1}  # the reload loop's probe, around line 229 (CHANGE-app-gateway.md)
ALLOWED_PARTS = {"testing": "the fakes", "remote_scripts": "runs inside Live and is its server"}

SOCKET_CALLS = {"socket", "create_connection", "create_server", "socketpair", "fromfd"}
HTTP_CALLS = {"urlopen", "HTTPConnection", "HTTPSConnection"}


def allowed(path: Path) -> bool:
    rel = path.relative_to(SRC).as_posix()
    return (
        rel in ALLOWED
        or rel in DEBT
        or path.name.endswith("_cli.py")
        or any(part in ALLOWED_PARTS for part in path.relative_to(SRC).parts)
    )


def violations(path: Path) -> list[str]:
    """Where a module constructs a LiveClient or opens a socket (or an HTTP connection)."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
        base = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
        if name == "LiveClient" or (base == "socket" and name in SOCKET_CALLS) or name in HTTP_CALLS:
            found.append(f"{path.relative_to(SRC)}:{node.lineno} calls {base + '.' if base else ''}{name}")
    return found


def library_files() -> list[Path]:
    return sorted(p for lib in LIBRARIES for p in (SRC / lib).rglob("*.py"))


def test_no_library_module_constructs_a_liveclient_or_opens_a_socket():
    bad = [v for p in library_files() if not allowed(p) for v in violations(p)]
    assert bad == [], "a library opened a connection; the app hands one in instead:\n" + "\n".join(bad)


def test_known_debt_does_not_grow_and_is_removed_when_paid():
    for rel, count in DEBT.items():
        found = len(violations(SRC / rel))
        assert found <= count, f"{rel} opens {found} connections; the list says {count}: do not add more"
        assert found == count, f"{rel} now opens {found}: update DEBT (remove it when it is 0)"


def test_the_check_sees_what_it_looks_for(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import socket\nfrom zpkt.live.transport import LiveClient\ns = socket.socket()\nc = LiveClient()\n")
    got = violations_in(f)
    assert len(got) == 2 and "socket.socket" in got[0] and "LiveClient" in got[1]


def violations_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            base = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
            if name == "LiveClient" or (base == "socket" and name in SOCKET_CALLS):
                out.append(f"{base + '.' if base else ''}{name}")
    return out


def test_the_allowed_list_is_short_and_every_entry_exists():
    for rel in ALLOWED:
        assert (SRC / rel).exists(), f"{rel} is allowed but not there: drop it from ALLOWED"
    assert len(ALLOWED) <= 6


def test_the_app_owns_the_connections():
    """The two places that build a LiveClient or bind a socket outside the libraries are the app's connections."""
    owners = {p.relative_to(SRC).as_posix() for p in (SRC / "app").rglob("*.py") if violations(p)}
    assert owners == {"app/connections.py"}


def test_adapters_do_not_import_zpkt_live_to_change_it():
    """An adapter reaches Live only through the bus: it imports no module that talks to Live."""
    for p in (SRC / "app" / "adapters").glob("*.py"):
        imported = {n.module for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.ImportFrom) and n.module}
        assert not [m for m in imported if m.startswith("zpkt.live")], f"{p.name} imports {imported}"


@pytest.mark.parametrize("lib", LIBRARIES)
def test_the_libraries_exist(lib):
    assert (SRC / lib / "__init__.py").exists()
