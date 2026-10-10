"""Automated-parameter state at given beats, read during playback, and its repair after cuts.

Delete Time drops an envelope whose breakpoints all fall inside the deleted range, and the
parameter then sits at its static value (HW002: the kick's scoop EQ stuck on). `restore` compares
every automated parameter at each kept segment's start with the uncut set and sets the static
ones back. A parameter path is [track index, device index, (… "c", chain index, device index),
parameter index], with the main track last among the tracks.
"""

from __future__ import annotations

import json
import time

from hands.live.transport import McpTransport

FIND = """
out = []
def walk(ti, tname, devs, path):
    for di, d in enumerate(devs):
        for pi, p in enumerate(d.parameters):
            if p.automation_state != 0:
                out.append({"track": tname, "device": d.name, "param": p.name, "path": path + [di, pi]})
        if getattr(d, "can_have_chains", False):
            for ci, ch in enumerate(d.chains):
                walk(ti, tname + "/" + ch.name, ch.devices, path + [di, "c", ci])
for ti, t in enumerate(list(song.tracks) + [song.master_track]):
    walk(ti, t.name, t.devices, [ti])
result = out
"""

GET = """
def get(path):
    t = (list(song.tracks) + [song.master_track])[path[0]]
    devs, i = t.devices, 1
    while True:
        d = devs[path[i]]
        if i + 1 < len(path) and path[i + 1] == "c":
            devs = d.chains[path[i + 2]].devices; i += 3; continue
        return d.parameters[path[i + 1]]
"""


def automated(client: McpTransport) -> list[dict]:
    """Every automated parameter: {"track", "device", "param", "path"}. Walks racks too."""
    return client.run(FIND)


def values_at(client: McpTransport, params: list[dict], beats: list[float]) -> dict[float, list[float]]:
    """{beat: [value per param]}, sampled one beat into each position. Plays the song (audio)."""
    out = {}
    paths = json.dumps([p["path"] for p in params])
    for beat in beats:
        client.run("song.stop_playing()")
        client.run("song.start_playing()")
        time.sleep(0.3)
        client.run(f"song.current_song_time = {beat + 1.0}")
        time.sleep(0.6)
        out[beat] = client.run(f"PATHS = {paths}\n" + GET + "result = [round(get(p).value, 4) for p in PATHS]")
        client.run("song.stop_playing()")
    return out


def set_static(client: McpTransport, path: list, value: float) -> None:
    """Set a parameter's static value, if it is not automated."""
    client.run(f"PATH = {json.dumps(path)}\n" + GET +
               f"p = get(PATH)\nif p.automation_state == 0:\n    p.value = {value}\nresult = p.automation_state")


def state(client: McpTransport, path: list) -> list:
    """[automation_state, value] of one parameter."""
    return client.run(f"PATH = {json.dumps(path)}\n" + GET + "p = get(PATH)\nresult = [p.automation_state, round(p.value, 4)]")


def restore(client: McpTransport, segs: list[tuple[int, int]], ref: dict, tol: float = 1e-3) -> list[tuple]:
    """Make every automated parameter at each segment's start match the uncut set.

    segs: the kept source bars [(first, last), ...], 1-based, in timeline order. ref: the uncut
    set's state, {"params": automated(...), "values": {str(source bar): [value per param]}}.
    A static parameter that differs is set back; a still-automated one, or one wanting
    different values at different starts, cannot be fixed this way and raises. Returns the
    (track, param) pairs it fixed.
    """
    names = [(p["track"], p["param"]) for p in ref["params"]]
    starts, pos = [], 0
    for a, b in segs:
        starts.append((a, pos * 4.0))
        pos += b - a + 1
    def mismatches() -> list[tuple[int, int]]:
        cur = values_at(client, ref["params"], [beat for _, beat in starts])
        return [(src, i) for src, beat in starts for i in range(len(names))
                if abs(cur[beat][i] - ref["values"][str(src)][i]) > tol]

    fixes = []
    bad = mismatches()
    for i in sorted({i for _, i in bad}):
        wants = {ref["values"][str(src)][i] for src, _ in starts}
        st, _ = state(client, ref["params"][i]["path"])
        if st != 0 or len(wants) != 1:
            raise RuntimeError(f"cannot fix {names[i]} statically: state {st}, wants {wants}")
        set_static(client, ref["params"][i]["path"], wants.pop())
        fixes.append(names[i])
    if bad and (still := mismatches()):
        raise RuntimeError(f"automation still differs: {[(names[i], src) for src, i in still]}")
    return fixes
