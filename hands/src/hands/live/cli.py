"""`hands live ...`: one-shot commands against the running Live, for shells and skills."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NoReturn

import typer

from hands import config
from hands.live.transport import DEFAULT_HOST, LiveClient, LiveError

app = typer.Typer(help="Drive the open Live set through the AbletonLiveMCP Remote Script.", no_args_is_help=True)

HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(None, "--port", help="Remote Script port (default: the rig's live_port, 16619).")


def _fail(message: str, code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise typer.Exit(code)


@app.command()
def audition(
    track: str = typer.Argument(..., help="Track name."),
    notes: str = typer.Option("69,72", help="Comma-separated MIDI notes."),
    listen: float = typer.Option(2.0, help="Seconds to read the meters."),
    force: bool = typer.Option(False, help="Audition even if Live is playing."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Play a chord on TRACK from a temporary arrangement clip, print meter peaks, clean up."""
    from hands.live.agent import audition as run_audition
    try:
        print(json.dumps(run_audition(LiveClient(host, port), track, [int(n) for n in notes.split(",")],
                                      listen_s=listen, force=force)))
    except LiveError as exc:
        _fail(str(exc))


@app.command()
def reload(
    set_path: Path = typer.Argument(..., help="The .als Live has open (after an offline edit)."),
    save_first: bool = typer.Option(False, "--save-first", help="Save Live before reopening (only if the file was NOT edited offline)."),
    seconds: int = typer.Option(10, help="Countdown length (the user can cancel)."),
) -> None:
    """Reopen SET_PATH in Live behind a cancellable countdown; wait for the bridge to answer."""
    import subprocess
    import time

    from hands.live import ui
    confirm = Path(__file__).resolve().parents[3] / "macros/hammerspoon/scripts/rig-confirm.sh"
    if save_first and not ui.menu("File", "Save Live Set"):
        _fail("could not save Live")
    if subprocess.run(["bash", str(confirm), f"Reloading the Live set {set_path.stem}", str(seconds)]).returncode != 0:
        _fail("cancelled (or no countdown)")
    subprocess.run(["open", "-a", config.rig().live_app, str(set_path)], check=True)
    time.sleep(3)
    for _ in range(60):
        try:
            if ui.dialogs():
                time.sleep(2)  # the set may still be loading behind a progress window
                continue
            LiveClient(retries=0, timeout=3).run("1")
            if ui.front_title() == set_path.stem:
                print(f"reloaded: {set_path.stem}")
                return
        except (LiveError, ui.UiError):
            pass
        time.sleep(2)
    if ui.dialogs():
        _fail("Live is showing a dialog, most likely about unsaved changes; answer it in Live, "
              "or save first (--save-first) when the file was not edited offline")
    _fail("Live did not show the set after the reload")


@app.command()
def ping(host: str = HOST, port: int | None = PORT,
         timeout: float = typer.Option(5.0, "--timeout", help="Seconds to wait for the pong.")) -> None:
    """Check that the Remote Script is listening (it answers from its own thread, not Live's)."""
    try:
        seconds = LiveClient(host, port, timeout=timeout, retries=0).ping()
    except LiveError as exc:
        _fail(str(exc))
    print(f"pong in {seconds * 1000:.0f} ms")


_IMPORT_SONG = re.compile(r"^\s*(import\s+song\b.*|from\s+song\s+import\b.*)$")
_PRINT_SHIM = """_printed = []
def print(*_a, sep=" ", end="\\n", **_k):
    _printed.append(sep.join(str(_x) for _x in _a))
"""
_PRINT_TAIL = """

if _printed and globals().get("result") is None:
    result = "\\n".join(_printed)
"""


_WRITES = re.compile(r"^(insert_|delete_|create_|duplicate_|set_|start_|stop_|continue_|fire|jump|tap_|undo|redo|"
                     r"load|move|add_|remove_|record|capture|quantize|clear|store|crop|paste|duplicate|append|"
                     r"re_enable|trigger|scrub|play|select)")
AGENT_READ_ONLY = ("`hands live exec` only reads Live when the Zpkt agent runs it, so this changed nothing. To change "
                   "levels, pans or devices, make a mix panel: hands panel make --spec '{\"name\": \"mix\", "
                   "\"bars\": [17, 8], \"faders\": [\"Kick bus\"], \"devices\": [{\"track\": \"Kick bus\", "
                   "\"device\": \"EQ Eight\", \"params\": {...}}]}'. It renders what it changed and `hands panel drop` "
                   "takes it out. For Live itself (a dialog, no sound): hands rig reset.")


def writes(source: str) -> bool:
    """Does this Live code change anything? An assignment to an attribute or item, a `del`, or a call of a method
    whose name changes Live (insert_device, delete_track, start_playing, ...). Code that does not parse is let
    through: Live reports the syntax error."""
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, (ast.Attribute, ast.Subscript)) and isinstance(sub.ctx, ast.Store):
                        return True
        if isinstance(node, ast.Delete):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if _WRITES.match(name) and name not in ("select_track",):
                return True
    return False


def friendly(source: str) -> tuple[str, list[str]]:
    """Forgive the two mistakes agents make most in Live code (2026-11-20, a 32-call loop): `import song`
    (song is already defined) and `print` (it shows nothing in Live; here it becomes the result)."""
    notes: list[str] = []
    lines = source.splitlines()
    kept = [line for line in lines if not _IMPORT_SONG.match(line)]
    if len(kept) != len(lines):
        notes.append("`song` is already defined in Live; `import song` was removed (never import it)")
    source = "\n".join(kept)
    if re.search(r"\bprint\s*\(", source):
        source = _PRINT_SHIM + source + _PRINT_TAIL
    return source, notes


@app.command("exec")
def exec_(
    code: str = typer.Argument(None, help="Python to run in Live: an expression, or statements that set `result`."),
    file: Path = typer.Option(None, "--file", help="Read the code from a file."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the code from stdin."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    raw: bool = typer.Option(False, "--raw", help="Don't prepend the helpers (param, set_norm, set_clamped, select_track)."),
    timeout: float = typer.Option(15.0, "--timeout", help="Seconds to wait for the reply."),
    retries: int = typer.Option(2, "--retries", help="Connection retries (a sent request is never resent)."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Run LOM code in Live and print its result. Exit 1 if Live raised or was not reachable."""
    try:
        source = file.read_text() if file else sys.stdin.read() if stdin else code
    except (OSError, UnicodeDecodeError) as exc:
        _fail(f"ERROR: cannot read the code ({exc})", 2)
    if not source or not source.strip():
        _fail("give the code as an argument, --file or --stdin", 2)
    if os.environ.get("ZPKT_AGENT") and writes(source):
        _fail(f"ERROR: {AGENT_READ_ONLY}")
    if not raw:
        from hands.live.agent import with_prelude
        source, notes = friendly(source)
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
        source = with_prelude(source)
    res = LiveClient(host, port, timeout=timeout, retries=retries).execute(source)
    if res.warning:
        print(f"warning: {res.warning}", file=sys.stderr)
    if res.status != "ok":
        _fail(f"ERROR: {res.error}" + (f"\n{res.traceback}" if res.traceback else ""))
    print(json.dumps(res.result) if as_json else res.result)


@app.command()
def check(
    expect: str = typer.Option(None, "--expect", help="The set that must be in front."),
    any_set: bool = typer.Option(False, "--any-set", help="Accept a set that is not one of ours (a desk session)."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Run the session guard: no dialog open, one of our sets in front, the LOM answering.
    Prints the front set; exit 1 with the reason if a check fails."""
    from hands.live import session

    try:
        print(session.check(LiveClient(host, port), "hands live check", expect_front=expect, ours=not any_set))
    except session.Guard as exc:
        _fail(f"GUARD: {exc}")


@app.command()
def export(
    out: Path = typer.Argument(..., help="File to write (.wav, .aif, .flac); a bare name goes to the rig's renders folder."),
    start: float = typer.Option(None, "--start", help="First beat to render; with --length, selected first."),
    length: float = typer.Option(None, "--length", help="Beats to render. Without a range, Live's own (loop brace or whole song)."),
    mode: str = typer.Option("Main", "--mode", help='"Main", a track name, "All Individual Tracks" or "Selected Tracks Only".'),
    bits: int = typer.Option(32, "--bits", help="16, 24 or 32."),
    sample_rate: int = typer.Option(44100, "--sample-rate"),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Render through Live's Export dialog and print the files written. Drives the GUI."""
    from hands.live import render, ui
    from hands.live.session import Guard

    if (start is None) != (length is None):
        _fail("give both --start and --length, or neither", 2)
    path = out if out.is_absolute() or len(out.parts) > 1 else config.rig().renders_dir / out
    try:
        written = render.export(LiveClient(host, port), path, start, length, mode=mode, bits=bits,
                                sample_rate=sample_rate)
    except (Guard, ui.UiError, LiveError, ValueError) as exc:
        _fail(f"export failed: {exc}")
    print("\n".join(str(f) for f in written))


@app.command()
def modals(reap: bool = typer.Option(False, "--reap", help="Press each safe button (Cancel, Don't Save, No, Close, OK).")) -> None:
    """List Live's modal dialogs (CLEAN if none, NO_LIVE if Live is not running); --reap dismisses
    the ones with a safe button and reports ABORT for any it will not touch."""
    from hands.live import ui

    try:
        found = ui.reap_modals(reap)
        own = ui.dialogs() if found.strip() == "CLEAN" else 0
    except ui.UiError as exc:
        _fail(str(exc))
    if own:  # Live draws its own prompts (Save changes?, Save As): no buttons to read or press from here
        found = f"OPEN | {own} dialog(s) Live draws itself; they cannot be read or pressed from here, look at Live"
    print(found)


# ---------------------------------------------------------------------------
# Harness efficiency extensions: reset, clip, device, surface

clip_app = typer.Typer(help="Manage arrangement MIDI clips and chord progressions.", no_args_is_help=True)
app.add_typer(clip_app, name="clip")

device_app = typer.Typer(help="Load, inspect, and configure devices on tracks.", no_args_is_help=True)
app.add_typer(device_app, name="device")

surface_app = typer.Typer(help="Bridge zpkt-surface JSON states directly into Live.", no_args_is_help=True)
app.add_typer(surface_app, name="surface")


@app.command()
def reset(
    track_name: str = typer.Option("Operator", "--track-name", help="Name for the single armed MIDI track."),
    tempo: float = typer.Option(None, "--tempo", help="Tempo in BPM."),
    force: bool = typer.Option(False, "--force", help="Reset even a set that has an arrangement or more than two tracks."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Reset the running Live set to a single named MIDI track. Deletes everything else: refuses a set
    with an arrangement or more than two tracks unless --force."""
    from hands.live.reset import reset_set
    try:
        res = reset_set(LiveClient(host, port), track_name=track_name, tempo=tempo, force=force)
        print(json.dumps(res))
    except (LiveError, RuntimeError) as exc:
        _fail(str(exc))


@clip_app.command("create")
def clip_create(
    track: str = typer.Argument(..., help="Track name or index."),
    chords: str = typer.Option(..., "--chords", help="Chord symbols or note numbers (e.g. 'Dm9,Bbmaj9,Gm9,C9')."),
    beats: float = typer.Option(32.0, "--beats", help="Clip length in beats."),
    start: float = typer.Option(0.0, "--start", help="Start position in beats."),
    name: str = typer.Option("Pattern", "--name", help="Clip name."),
    rhythm: str = typer.Option("staccato-16ths", "--rhythm", help="Rhythm preset or comma-separated beat offsets."),
    velocity: int = typer.Option(110, "--velocity", help="Base velocity (1-127)."),
    duration: float = typer.Option(None, "--duration", help="Note duration in beats."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Create an arrangement MIDI clip with chords and rhythm in one atomic call."""
    from hands.live import midi
    try:
        prog = midi.parse_progression(chords)
        notes = midi.generate_clip_notes(prog, beats=beats, rhythm=rhythm, base_velocity=velocity, duration=duration)
        res = midi.create_arrangement_clip(LiveClient(host, port), track=track, start=start, length=beats, name=name, notes=notes)
        print(json.dumps(res))
    except (ValueError, LiveError) as exc:
        _fail(str(exc))


@device_app.command("load")
def device_load(
    track: str = typer.Argument(..., help="Track name or index."),
    device_name: str = typer.Argument(..., help="Device name from Live browser (e.g. 'Operator')."),
    category: str = typer.Option("instruments", "--category", help="'instruments' or 'audio_effects'."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Load a device onto a track from the Live browser."""
    from hands.live import device
    try:
        res = device.load_device(LiveClient(host, port), track=track, device_name=device_name, category=category)
        print(json.dumps(res))
    except (ValueError, LiveError) as exc:
        _fail(str(exc))


@device_app.command("set")
def device_set(
    track: str = typer.Argument(..., help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index on track."),
    param: list[str] = typer.Option([], "--param", help="NAME=VALUE parameter pairs (repeatable)."),
    json_params: str = typer.Option(None, "--json", help="JSON dictionary of parameter name/value pairs."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Batch-set parameters on a device in a single atomic call."""
    from hands.live import device as dev_mod
    p_dict = {}
    if json_params:
        try:
            p_dict.update(json.loads(json_params))
        except json.JSONDecodeError as exc:
            _fail(f"Invalid JSON: {exc}", 2)
    for p in param:
        if "=" not in p:
            _fail(f"Invalid parameter pair {p!r}; must be NAME=VALUE", 2)
        k, v = p.split("=", 1)
        try:
            p_dict[k.strip()] = float(v.strip())
        except ValueError:
            p_dict[k.strip()] = v.strip()
    try:
        res = dev_mod.set_parameters(LiveClient(host, port), track=track, device=device, params=p_dict)
        print(json.dumps(res))
    except LiveError as exc:
        _fail(str(exc))


@device_app.command("list")
def device_list(
    track: str = typer.Argument(..., help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index on track."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """List parameters on a device with their ranges and values."""
    from hands.live import device as dev_mod
    try:
        res = dev_mod.list_parameters(LiveClient(host, port), track=track, device=device)
        print(json.dumps(res))
    except LiveError as exc:
        _fail(str(exc))


@surface_app.command("apply")
def surface_apply(
    state: str = typer.Argument(..., help="zpkt-surface JSON string or path to JSON file."),
    track: str = typer.Option("0", "--track", help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index."),
    map_json: str = typer.Option(None, "--map", help="Optional JSON mapping surface IDs to device parameter names."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Apply zpkt-surface state to Live device and mixer parameters."""
    from hands.live import surface
    state_str = state
    p = Path(state)
    if p.is_file():
        state_str = p.read_text()
    try:
        state_dict = json.loads(state_str)
    except json.JSONDecodeError as exc:
        _fail(f"Invalid JSON: {exc}", 2)
    custom_map = json.loads(map_json) if map_json else None
    try:
        res = surface.apply_surface_state(LiveClient(host, port), state=state_dict, track=track, device=device, mapping=custom_map)
        print(json.dumps(res))
    except LiveError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------------------
# The set as a file, and its mix state as data: save, state take/diff/put/ls

state_app = typer.Typer(help="The mix state of the open set as data: take it, compare it, put it back.",
                        no_args_is_help=True)
app.add_typer(state_app, name="state")


def _front_set() -> str:
    """The open set's name: Live's window title, else (window on another Space, full screen) the set hands
    last saw Live open or save, which a `hands live ...` command keeps on disk."""
    from hands.live import session, ui
    try:
        if title := ui.front_title():
            return title
    except ui.UiError:
        pass
    try:
        seen = json.loads(session._loaded_file().read_text())
    except (FileNotFoundError, ValueError):
        seen = {}
    if seen:
        name = max(seen, key=seen.get)
        print(f"(Live's window is not readable: using {name}, the set hands last saw open)", file=sys.stderr)
        return name
    _fail("Live shows no set, and hands has not seen one opened or saved")


@app.command("open")
def open_(
    name: str = typer.Argument(..., help="A set in the rig's sets folder, without .als."),
    no_save: bool = typer.Option(False, "--no-save", help="Do not save the set in front first."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Open a set and wait until it is in front and the LOM answers. The set in front is saved first."""
    from hands.live import session
    try:
        seconds = session.open_set(LiveClient(host, port), name.removesuffix(".als"), save_current=not no_save)
    except session.Guard as exc:
        _fail(str(exc))
    print(f"opened {name} in {seconds:.1f} s")


@app.command()
def save(
    as_: str = typer.Option(None, "--as", help="Also keep a copy as sets_dir/<AS>.als (refuses to replace one)."),
    state: str = typer.Option(None, "--state", help="Also take the mix state as NAME (see `hands live state`)."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """File > Save Live Set on the front set and wait for its file; optionally keep a named copy and its state."""
    from hands.live import session
    from hands.live import state as S
    name = _front_set()
    if as_ and config.rig().set_path(as_).exists():
        _fail(f"{config.rig().set_path(as_)} exists; pick another name")
    wrote = session.save(name)
    print(f"{'saved' if wrote else 'nothing to save in'} {config.rig().set_path(name)}")
    if as_:
        print(f"copy {session.copy_set(name, as_)}")
    if state:
        p = S.save(S.take(LiveClient(host, port, keep=True)), S.path_for(name, state), name)
        print(f"state {p}")


@state_app.command("take")
def state_take(
    name: str = typer.Argument(..., help="State name (or a .json path)."),
    only: list[str] = typer.Option(None, "--only", help="Only these tracks (repeatable)."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Every mixer and device value of the front set -> sets_dir/state/<set>/NAME.json."""
    from hands.live import state as S
    set_name = _front_set()
    t0 = time.monotonic()
    st = S.take(LiveClient(host, port, keep=True), only)
    p = S.save(st, S.path_for(set_name, name), set_name)
    print(f"{p}  ({len(st['tracks'])} tracks, {len(S.flatten(st))} values, "
          f"{time.monotonic() - t0:.1f} s)")


@state_app.command("diff")
def state_diff(
    a: str = typer.Argument(..., help="A state name, a state .json, or a recipe .json with a \"desk\"."),
    b: str = typer.Argument(None, help="Another one; default: Live now."),
    ignore: list[str] = typer.Option(None, "--ignore", help="Skip keys starting with this (e.g. 'mon '), repeatable."),
    full: bool = typer.Option(False, "--full", help="Every row, not the collapsed summary."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """What differs between A and B (or Live now). Only tracks A holds are read from Live. Exit 1 if anything does."""
    from hands.live import state as S
    set_name = _front_set() if b is None or not b.endswith(".json") or not a.endswith(".json") else ""
    sa = S.load(S.path_for(set_name, a))
    if b is None:
        sb = S.take(LiveClient(host, port, keep=True), only=list(sa["tracks"]))
    else:
        sb = S.load(S.path_for(set_name, b))
    rows = S.diff(sa, sb, tuple(ignore or ()))
    n = len(S.flatten(sa))
    print(f"{n} values in A, {len(rows)} differ")
    print(S.summarize(rows, limit=10**6 if full else 60))
    if rows:
        raise typer.Exit(1)


@state_app.command("put")
def state_put(
    name: str = typer.Argument(..., help="A state name or .json (a recipe with a \"desk\" works too)."),
    only: list[str] = typer.Option(None, "--only", help="Only these tracks (repeatable)."),
    host: str = HOST, port: int | None = PORT,
) -> None:
    """Write a state's raw values into Live, read them back; exit 1 with what still differs."""
    from hands.live import hold
    from hands.live import state as S
    set_name = _front_set()
    st = S.load(S.path_for(set_name, name))
    with hold.using_live(f"hands live state put {name}"):
        rows = S.put(LiveClient(host, port, keep=True), st, only)
    print("put, Live matches" if not rows else f"{len(rows)} differ after put:\n{S.summarize(rows)}")
    if rows:
        raise typer.Exit(1)


@state_app.command("ls")
def state_ls() -> None:
    """The states kept for the front set, newest first."""
    from hands.live import state as S
    d = S.folder(_front_set())
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []
    print("\n".join(f"{p.stem:30s} {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}"
                    for p in files) or f"none in {d}")
