"""Tracks by name, as Live names them: Main, and returns with Live's letter in front ("A-Space").

The one rule, used by hands' code strings, zpkt.live.state and the mix desk's pager: "Main" or "Master" (any case)
is the master track; otherwise the first track or return with exactly that name; otherwise a return whose name
without its letter is that name. So "Space" finds the return "A-Space", and a state keyed by "Space" still fits after
returns are added or reordered. `find_track` runs where `song` is; `track_expr` is the same rule as one LOM
expression, for code strings and panel files that hold an expression rather than this module.

Stdlib only, Python 3.11: this file also runs inside Live (zpkt.live.inlive).
"""

MAIN_NAMES = ("main", "master")


def is_main(name: str) -> bool:
    """Is `name` how zpkt names the master track ("Main", or Live's older "Master")?"""
    return str(name).strip().lower() in MAIN_NAMES


def short_name(name: str, is_return: bool) -> str:
    """A return's name without the letter Live puts in front ("A-Space" -> "Space"); other names as they are."""
    return name[2:] if is_return and len(name) > 2 and name[1] == "-" else name


def find_track(song, name: str):  # song: Live's Song
    """The track, return or Main that `name` names (the module docstring has the rule); LookupError if none."""
    if is_main(name):
        return song.master_track
    for track in list(song.tracks) + list(song.return_tracks):
        if track.name == name:
            return track
    for track in song.return_tracks:
        if short_name(track.name, True) == name:
            return track
    raise LookupError(f"no track, return or Main named {name!r}")


def track_expr(name: str) -> str:
    """The rule of `find_track` as one LOM expression (StopIteration in Live if nothing matches)."""
    if is_main(name):
        return "song.master_track"
    return (
        f"next(iter([t for t in list(song.tracks) + list(song.return_tracks) if t.name == {name!r}]"
        f" + [t for t in song.return_tracks if len(t.name) > 2 and t.name[1] == '-' and t.name[2:] == {name!r}]))"
    )
