"""A state key's parameter in the open set: the one resolver from a key (zpkt.live.inlive.keys) to the LOM.

    find_value(song, "Kick bus/desk EQ/1 Gain A")   # a device parameter
    find_value(song, "Kick bus/send Space")         # a send
    find_value(song, "Kick bus/volume")             # mixer volume or pan
    find_value(song, "Kick bus/mute")               # a track's flag: (track, "mute"), not a parameter

A key is "TRACK/REST". REST is "volume", "pan", "mute", "solo", "send RETURN", or "DEVICE/PARAM" where PARAM may hold
a slash ("Dry/Wet") and DEVICE may end in "#2" for the second device of that name. A track's name may not hold a
slash. `selection_key` goes the other way, for what is selected in Live.

Stdlib only, Python 3.11: this file also runs inside Live (zpkt.live.inlive), and imports no other inlive module.
"""

FLAGS = ("mute", "solo")


def split_key(key: str) -> tuple[str, str]:
    """(track, rest) of a key; ValueError if it has no slash."""
    track, slash, rest = str(key).partition("/")
    if not slash or not track or not rest:
        raise ValueError(f"{key!r} is not a state key: it needs TRACK/VALUE")
    return track, rest


def _track(song, name: str):
    if str(name).strip().lower() in ("main", "master"):
        return song.master_track
    for t in list(song.tracks) + list(song.return_tracks):
        if t.name == name:
            return t
    for t in song.return_tracks:
        if len(t.name) > 2 and t.name[1] == "-" and t.name[2:] == name:
            return t
    raise LookupError(f"no track, return or Main named {name!r}")


def _device(track, label: str):
    """The device a key's label names: the name as it is, else NAME#N as the Nth device of that name."""
    named = [d for d in track.devices if d.name == label]
    if named:
        return named[0]
    name, hash_, nth = label.rpartition("#")
    if hash_ and nth.isdigit() and int(nth) >= 1:
        named = [d for d in track.devices if d.name == name]
        if len(named) >= int(nth):
            return named[int(nth) - 1]
    raise LookupError(f"{track.name!r} has no device {label!r}; it has: {', '.join(d.name for d in track.devices)}")


def find_value(song, key):  # song: Live's Song
    """The DeviceParameter `key` names, or (track, "mute" | "solo") for a flag; LookupError saying what is missing."""
    name, rest = split_key(key)
    track = _track(song, name)
    mixer = track.mixer_device
    if rest == "volume":
        return mixer.volume
    if rest == "pan":
        return mixer.panning
    if rest in FLAGS:
        if track is song.master_track:
            raise LookupError(f"Main has no {rest}")
        return track, rest
    if rest.startswith("send "):
        want = rest[5:]
        for k, r in enumerate(song.return_tracks):
            if r.name == want or (len(r.name) > 2 and r.name[1] == "-" and r.name[2:] == want):
                return mixer.sends[k]
        raise LookupError(f"no return named {want!r}")
    label, slash, param = rest.partition("/")
    if not slash:
        raise LookupError(f"{key!r}: {rest!r} is not volume, pan, mute, solo, a send or DEVICE/PARAM")
    device = _device(track, label)
    for p in device.parameters:
        if p.name == param:
            return p
    raise LookupError(f"{track.name}/{label} has no parameter {param!r}")


def track_name_in_key(song, track) -> str:
    """A track's name as keys spell it: "Main", a return without Live's letter, else its name."""
    if track is song.master_track:
        return "Main"
    if track in list(song.return_tracks) and len(track.name) > 2 and track.name[1] == "-":
        return track.name[2:]
    return track.name


def selection_key(song) -> dict[str, str | None]:
    """What is selected in Live, as {"track", "device", "param", "key"}: names as keys spell them, None where nothing
    is selected, and "key" for the selected parameter when it is one a key can name (a device at the top of the
    track's chain; a device inside a rack has no key)."""
    view = song.view
    track = view.selected_track
    out: dict[str, str | None] = {"track": None, "device": None, "param": None, "key": None}
    if track is None:
        return out
    out["track"] = track_name_in_key(song, track)
    device = track.view.selected_device
    if device is None:
        return out
    top = list(track.devices)
    label = None
    if device in top:
        same = [d for d in top if d.name == device.name]
        nth = same.index(device) + 1
        label = device.name if nth == 1 else f"{device.name}#{nth}"
    out["device"] = label or device.name
    param = getattr(view, "selected_parameter", None)
    if param is None or label is None or param not in list(device.parameters):
        return out
    out["param"] = param.name
    out["key"] = f"{out['track']}/{label}/{param.name}"
    return out
