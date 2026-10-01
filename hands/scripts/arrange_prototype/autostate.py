"""Automated-parameter state at given beats, read during playback.

Used to restore automation state that Delete Time loses: when every
breakpoint of an envelope falls inside a deleted range, Live drops the
envelope and the parameter falls back to its static value.
"""
import json
import time

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


def automated(r):
    return r(FIND)


def values_at(r, params, beats):
    """{beat: [value per param]} sampled one beat into each position."""
    out = {}
    for beat in beats:
        r("song.stop_playing()"); r("song.start_playing()"); time.sleep(0.3)
        r(f"song.current_song_time = {beat + 1.0}"); time.sleep(0.6)
        out[beat] = r(f"PATHS = {json.dumps([p['path'] for p in params])}\n" + GET +
                      "result = [round(get(p).value, 4) for p in PATHS]")
        r("song.stop_playing()")
    return out


def set_static(r, path, value):
    r(f"PATH = {json.dumps(path)}\n" + GET + f"p = get(PATH)\nif p.automation_state == 0:\n    p.value = {value}\nresult = p.automation_state")


def state(r, path):
    return r(f"PATH = {json.dumps(path)}\n" + GET + "p = get(PATH)\nresult = [p.automation_state, round(p.value, 4)]")
