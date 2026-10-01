"""A/B against reference tracks, and show a spectrum analyzer.

Reference tracks are audio tracks named "REF <name>", kept muted while the mix
plays (see docs/hw002/references.md). Listening to a reference unmutes and
solos it, so the mix goes quiet without touching its own mutes. Going back
unsolos and re-mutes every reference.

Each action is one LOM round trip, so a hotkey answers quickly. The set
remembers the current reference in its song data under DATA_KEY.
"""

from __future__ import annotations

from typing import Any

from hands.transport import McpTransport

REF_PREFIX = "REF "
DATA_KEY = "zpkt.ab.ref"
SPECTRUM_CLASS = "SpectrumAnalyzer"

_PRELUDE = f"""
refs = [t for t in song.tracks if t.name.startswith({REF_PREFIX!r})]
if not refs:
    raise RuntimeError("no reference tracks: name them {REF_PREFIX}<name>")
names = [t.name for t in refs]
saved = song.get_data({DATA_KEY!r}, "")
cur = refs[names.index(saved)] if saved in names else refs[0]
listening = any(t.solo and not t.mute for t in refs)
"""

_SPECTRUM = f"""
app = Live.Application.get_application()
master = song.master_track
spec = next((d for d in master.devices if d.class_name == {SPECTRUM_CLASS!r}), None)
if spec is None:
    spec = master.insert_device("Spectrum")
shown = (app.view.is_view_visible("Detail/DeviceChain")
         and song.view.selected_track == master
         and master.view.selected_device == spec)
if TOGGLE and shown:
    app.view.hide_view("Detail")
    spectrum = False
else:
    song.view.selected_track = master
    song.view.select_device(spec)
    app.view.show_view("Detail/DeviceChain")
    spectrum = True
"""

_LISTEN_REF = """
for t in refs:
    t.solo = False
    t.mute = True
cur.mute = False
cur.solo = True
"""

_LISTEN_MIX = """
for t in refs:
    t.solo = False
    t.mute = True
"""


def _run(transport: McpTransport, body: str) -> dict[str, Any]:
    res = transport.execute(body)
    if res.status != "ok":
        raise RuntimeError(res.error or "Live did not answer")
    return dict(res.result or {})


def _with_spectrum(body: str, spectrum: bool, toggle: bool) -> str:
    if not spectrum:
        return body + "\nresult['spectrum'] = None\n"
    return body + f"\nTOGGLE = {toggle!r}\n" + _SPECTRUM + "\nresult['spectrum'] = spectrum\n"


def toggle(transport: McpTransport, spectrum: bool = False) -> dict[str, Any]:
    """Switch between the mix and the current reference."""
    body = _PRELUDE + f"""
if listening:
{_indent(_LISTEN_MIX)}
    mode = "mix"
else:
{_indent(_LISTEN_REF)}
    mode = "ref"
result = {{"mode": mode, "ref": cur.name}}
"""
    return _run(transport, _with_spectrum(body, spectrum, toggle=False))


def next_ref(transport: McpTransport) -> dict[str, Any]:
    """Make the next reference current; if one is playing, switch to it."""
    body = _PRELUDE + f"""
cur = refs[(refs.index(cur) + 1) % len(refs)]
song.set_data({DATA_KEY!r}, cur.name)
if listening:
{_indent(_LISTEN_REF)}
result = {{"mode": "ref" if listening else "mix", "ref": cur.name}}
"""
    return _run(transport, _with_spectrum(body, False, False))


def status(transport: McpTransport) -> dict[str, Any]:
    body = _PRELUDE + """
result = {"mode": "ref" if listening else "mix", "ref": cur.name, "refs": names}
"""
    return _run(transport, body)


def spectrum(transport: McpTransport, toggle: bool = True) -> dict[str, Any]:
    """Show the master Spectrum (adding it if missing); with toggle, hide it if shown."""
    return _run(transport, _with_spectrum("result = {}\n", True, toggle))


def _indent(code: str) -> str:
    return "\n".join("    " + line if line.strip() else line for line in code.strip("\n").splitlines())
