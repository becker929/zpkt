"""`hands live reset|clip|device|surface`: build a set from the shell, one atomic LOM call each."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from hands.live.cli_options import HOST, PORT, fail
from hands.live.transport import LiveClient, LiveError

clip_app = typer.Typer(help="Manage arrangement MIDI clips and chord progressions.", no_args_is_help=True)
device_app = typer.Typer(help="Load, inspect, and configure devices on tracks.", no_args_is_help=True)
surface_app = typer.Typer(
    help="Apply a zpkt-surface state to one device's parameters, guessing units from the control ids.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    app.command()(reset)
    app.add_typer(clip_app, name="clip")
    app.add_typer(device_app, name="device")
    app.add_typer(surface_app, name="surface")


def reset(
    track_name: str = typer.Option("Operator", "--track-name", help="Name for the single armed MIDI track."),
    tempo: float = typer.Option(None, "--tempo", help="Tempo in BPM."),
    force: bool = typer.Option(
        False, "--force", help="Reset even a set that has an arrangement or more than two tracks."
    ),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Reset the running Live set to a single named MIDI track. Deletes everything else: refuses a set
    with an arrangement or more than two tracks unless --force."""
    from hands.live.reset import reset_set

    try:
        res = reset_set(LiveClient(host, port), track_name=track_name, tempo=tempo, force=force)
        print(json.dumps(res))
    except (LiveError, RuntimeError) as exc:
        fail(str(exc))


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
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Create an arrangement MIDI clip with chords and rhythm in one atomic call."""
    from hands.live import midi

    try:
        prog = midi.parse_progression(chords)
        notes = midi.generate_clip_notes(prog, beats=beats, rhythm=rhythm, base_velocity=velocity, duration=duration)
        res = midi.create_arrangement_clip(
            LiveClient(host, port), track=track, start=start, length=beats, name=name, notes=notes
        )
        print(json.dumps(res))
    except (ValueError, LiveError) as exc:
        fail(str(exc))


@device_app.command("load")
def device_load(
    track: str = typer.Argument(..., help="Track name or index."),
    device_name: str = typer.Argument(..., help="Device name from Live browser (e.g. 'Operator')."),
    category: str = typer.Option("instruments", "--category", help="'instruments' or 'audio_effects'."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Load a device onto a track from the Live browser."""
    from hands.live import device

    try:
        res = device.load_device(LiveClient(host, port), track=track, device_name=device_name, category=category)
        print(json.dumps(res))
    except (ValueError, LiveError) as exc:
        fail(str(exc))


@device_app.command("set")
def device_set(
    track: str = typer.Argument(..., help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index on track."),
    param: list[str] = typer.Option([], "--param", help="NAME=VALUE parameter pairs (repeatable)."),
    json_params: str = typer.Option(None, "--json", help="JSON dictionary of parameter name/value pairs."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Batch-set parameters on a device in a single atomic call."""
    from hands.live import device as dev_mod

    p_dict = {}
    if json_params:
        try:
            p_dict.update(json.loads(json_params))
        except json.JSONDecodeError as exc:
            fail(f"Invalid JSON: {exc}", 2)
    for p in param:
        if "=" not in p:
            fail(f"Invalid parameter pair {p!r}; must be NAME=VALUE", 2)
        k, v = p.split("=", 1)
        try:
            p_dict[k.strip()] = float(v.strip())
        except ValueError:
            p_dict[k.strip()] = v.strip()
    try:
        res = dev_mod.set_parameters(LiveClient(host, port), track=track, device=device, params=p_dict)
        print(json.dumps(res))
    except LiveError as exc:
        fail(str(exc))


@device_app.command("list")
def device_list(
    track: str = typer.Argument(..., help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index on track."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """List parameters on a device with their ranges and values."""
    from hands.live import device as dev_mod

    try:
        res = dev_mod.list_parameters(LiveClient(host, port), track=track, device=device)
        print(json.dumps(res))
    except LiveError as exc:
        fail(str(exc))


@surface_app.command("apply")
def surface_apply(
    state: str = typer.Argument(..., help="zpkt-surface JSON string or path to JSON file."),
    track: str = typer.Option("0", "--track", help="Track name or index."),
    device: str = typer.Option("0", "--device", help="Device name or index."),
    map_json: str = typer.Option(None, "--map", help="Optional JSON mapping surface IDs to device parameter names."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Apply a zpkt-surface state to a device. It guesses each parameter and its units (Hz, ms) from the control
    ids; `hands panel apply` sets values by what Live shows instead."""
    from hands.live import surface

    state_str = state
    p = Path(state)
    if p.is_file():
        state_str = p.read_text()
    try:
        state_dict = json.loads(state_str)
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON: {exc}", 2)
    custom_map = json.loads(map_json) if map_json else None
    try:
        res = surface.apply_surface_state(
            LiveClient(host, port), state=state_dict, track=track, device=device, mapping=custom_map
        )
        print(json.dumps(res))
    except LiveError as exc:
        fail(str(exc))
