"""E4: Bounce to New Track and Paste Bounced Audio as a render path for probes.

  cd ~/Desktop/zpkt/hands && uv run python scripts/probe_pack/bench_e4_bounce.py PART [PART ...]

Run on 2026-10-06 in this order:
  open probe bounce1 clean1 bounce2(guard: item disabled) reactivate export_now export_fresh
  bounce_fresh paste(guard: Paste Bounced Audio disabled) del_placeholder bounce_loop final analyse

open          copy HW002_121_pp_v01 -> HW002_121_pp_b (once) and open it fresh
probe         read-only: select lanes, print Edit-menu bounce labels and tracks
bounce1       first render after load: LOM-select perc group + Select Loop (8..88) + Edit > Bounce
clean1        delete the '(Bounce)' tracks (one LOM call)
bounce2       variant: re-select the group over LOM after Select Loop -> bounce item disabled
reactivate    Bounce deactivates (clip.muted) the source clips in range; set them active again
export_now    Export 'All Individual Tracks' 8..88 (warm)        -> e4/exp_warm2 *
export_fresh  save, open pp_h, reopen, export as first render     -> e4/exp_fresh *
bounce_fresh  save, open pp_h, reopen, bounce as first render     -> e4/bounce3__*
paste         Copy + Paste Bounced Audio onto an empty audio track (stays disabled; see report)
bounce_loop   per probe: one LOM call (reactivate, drop old bounces, Reverb Dry/Wet) + Select Loop
              + Edit > Bounce Groups to New Tracks                -> e4/bloop<k>__*
final         remove the Reverb, verify restored, save
analyse       lag / residual / features for the pairs above       -> e4/compare.jsonl

Gotchas: Edit-menu titles/enabled flags read over AX are a snapshot Live rewrites asynchronously after
a menu action, and LOM selection changes do not refresh them; resolve the item title right before the
click (stable_labels_for). Select Loop puts the time range on every lane, so Bounce renders every group.
Every Live step is wrapped in pp.check before and after; any Guard or error stops the run.
"""
import os
import shutil
import sys
import threading
import time
from collections import Counter

import pp
from pp import A, log

NAME = "HW002_121_pp_b"
AWAY = "HW002_121_pp_h"          # scratch set used to force a fresh load of NAME
START, LEN = 8.0, 80.0           # the 20-bar shape after the 2-bar lead-in (160 BPM -> 30 s)
SAMPLES = os.path.join(pp.PROJ, "Samples")
OUT = pp.DATA + "e4/"
KICK, PERC = "S01 kick group", "S01 perc group"


# ---------------------------------------------------------------- small helpers
def edit_items():
    s = A.osa('tell application "System Events" to tell process "Live" to get name of every menu item of menu "Edit" of menu bar 1')
    return [x.strip() for x in s.split(",")]


def edit_enabled(item):
    return A.osa(f'tell application "System Events" to tell process "Live" to get enabled of menu item "{item}" of menu "Edit" of menu bar 1') == "true"


def bounce_labels():
    return [i for i in edit_items() if i.startswith("Bounce")]


def stable_labels(timeout=4.0):
    """Live rewrites Edit-menu titles asynchronously after a menu action (a read right after Select
    Loop can still show 'Bounce Group to New Track'). Wait for two equal reads 0.3 s apart."""
    t = time.time()
    prev = bounce_labels()
    while time.time() - t < timeout:
        time.sleep(0.3)
        cur = bounce_labels()
        if cur == prev:
            return cur
        prev = cur
    return prev


def stable_labels_for(hold=1.0, timeout=6.0):
    """Labels unchanged for `hold` seconds (reads every 0.25 s)."""
    t = time.time()
    prev, since = bounce_labels(), time.time()
    while time.time() - t < timeout:
        time.sleep(0.25)
        cur = bounce_labels()
        if cur != prev:
            prev, since = cur, time.time()
        elif time.time() - since >= hold:
            return cur
    return prev


def select_lane(track, start=START, length=LEN):
    """One LOM call (select the track, focus the Arranger, set the loop brace), then Edit > Select Loop."""
    sel = A.r(f'''
song.stop_playing()
app = Live.Application.get_application()
app.view.show_view("Arranger")
app.view.focus_view("Arranger")
song.view.selected_track = [t for t in song.tracks if t.name == {track!r}][0]
song.loop_start = {float(start)}
song.loop_length = {float(length)}
result = song.view.selected_track.name''')
    if not A.menu("Edit", "Select Loop"):
        raise pp.Guard("Edit > Select Loop disabled")
    time.sleep(0.3)
    return sel


def tracks():
    return A.r('''
out = []
for i, t in enumerate(song.tracks):
    clips = [] if t.is_foldable else [(round(c.start_time, 3), round(c.end_time, 3), c.name, getattr(c, "file_path", None) if c.is_audio_clip else None) for c in t.arrangement_clips]
    out.append({"i": i, "name": t.name, "group": t.is_foldable, "audio": t.has_audio_input and not t.is_foldable,
                "grouped": t.is_grouped, "mute": t.mute, "n": len(clips), "clips": clips})
result = out''')


WINS_OSA = '''tell application "System Events" to tell process "Live"
  set out to {}
  repeat with w in every window
    try
      set end of out to ((name of w) as text) & "|" & ((subrole of w) as text)
    end try
  end repeat
  set AppleScript's text item delimiters to ";"
  return out as text
end tell'''


class Watch(threading.Thread):
    """Background: record every Live window (name|subrole) seen while a render runs."""
    def __init__(self):
        super().__init__(daemon=True)
        self.halt, self.seen, self.t0 = False, {}, time.time()

    def run(self):
        while not self.halt:
            try:
                s = A.osa(WINS_OSA)
            except Exception as e:          # noqa: BLE001  (record, keep watching)
                s = f"osa-error {type(e).__name__}|"
            for w in s.split(";"):
                if w and w not in self.seen:
                    self.seen[w] = round(time.time() - self.t0, 2)
            time.sleep(0.15)

    def stop(self):
        self.halt = True
        self.join(timeout=35)
        return self.seen


def snap():
    out = {}
    for root, _, files in os.walk(SAMPLES):
        for f in files:
            p = os.path.join(root, f)
            try:
                out[p] = os.path.getsize(p)
            except FileNotFoundError:
                pass
    return out


def wav_info(p):
    import soundfile as sf
    i = sf.info(p)
    return {"sr": i.samplerate, "ch": i.channels, "subtype": i.subtype, "format": i.format,
            "frames": i.frames, "dur_s": round(i.frames / i.samplerate, 4), "mb": round(os.path.getsize(p) / 1e6, 2)}


# ---------------------------------------------------------------- parts
def part_open():
    pp.check("e4 open: start")
    dst = os.path.join(pp.PROJ, NAME + ".als")
    if not os.path.exists(dst):
        pp.copy_set("HW002_121_pp_v01", NAME)
    if A.front() == NAME:
        raise pp.Guard(f"{NAME} already in front; switch away first for a fresh load")
    pp.prepare_switch()
    t = time.time()
    pp.open_set(NAME)
    log("e4_load", time.time() - t, set=NAME, **pp.live_footprint_gb())
    pp.check("e4 open: loaded", expect_front=NAME)


def part_probe():
    pp.check("e4 probe: start", expect_front=NAME)
    print("labels before:", bounce_labels(), flush=True)
    for tr in (PERC, KICK):
        sel = select_lane(tr)
        print(tr, "-> selected", sel, "labels", bounce_labels(),
              "paste-bounced enabled", edit_enabled("Paste Bounced Audio"), flush=True)
    print(A.r(f'''
g = [t for t in song.tracks if t.name == {PERC!r}][0]
result = {{"devices": [d.class_name + ":" + d.name for d in g.devices], "vol": g.mixer_device.volume.value,
          "sr": song.view.selected_track.name, "loop": [song.loop_start, song.loop_length, song.loop],
          "last_event": song.last_event_time}}'''), flush=True)
    for t in tracks():
        print({k: v for k, v in t.items() if k != "clips"}, flush=True)
    pp.check("e4 probe: end", expect_front=NAME)


PER_FILE = {}                      # path -> [first seen, last growth] (s after the click), last render


def wait_render(before, t0, timeout=120.0, settle=1.0):
    """Poll Samples/ until new .wav files appear and stop changing for `settle` s.
    Returns (files {path: size}, t_first, t_last_change) in seconds after t0."""
    t_first = t_last = None
    last = None
    PER_FILE.clear()
    while time.time() - t0 < timeout:
        cur = snap()
        new = {p: s for p, s in cur.items() if p.endswith(".wav") and before.get(p) != s}
        now = time.time() - t0
        for p, s in new.items():
            if p not in PER_FILE:
                PER_FILE[p] = [round(now, 2), round(now, 2), s]
            elif PER_FILE[p][2] != s:
                PER_FILE[p][1:] = [round(now, 2), s]
        if new:
            if t_first is None:
                t_first = now
            if new != last:
                last, t_last = new, now
            elif now - t_last >= settle:
                return new, t_first, t_last
        time.sleep(0.05)
    return last or {}, t_first, t_last


def wait_no_dialog(timeout=20.0):
    t = time.time()
    while time.time() - t < timeout:
        if pp.dialogs() == 0:
            return time.time() - t
        time.sleep(0.25)
    raise pp.Guard(f"a dialog stayed open {timeout:.0f} s after the render")


def run_menu_render(tag, label, expect_new_tracks=None):
    """Click an Edit-menu render command, time it to the written file(s), then read the new
    tracks/clips over LOM. Returns a dict with timings, new tracks/clips and copied files."""
    pp.check(f"{tag}: before click", expect_front=NAME)
    tr0 = tracks()
    names0 = [t["name"] for t in tr0]
    clips0 = {(t["name"], c[0], c[2]) for t in tr0 for c in t["clips"]}
    if callable(label):                    # resolve the (asynchronously retitled) item right before the click
        label = label()
    before = snap()
    w = Watch()
    w.start()
    t0 = time.time()
    ok = A.menu("Edit", label)
    t_click = time.time() - t0
    if not ok:
        w.stop()
        raise pp.Guard(f"{tag}: Edit > {label!r} disabled; labels now {bounce_labels()}")
    files, t_first, t_last = wait_render(before, t0)
    t_files = time.time() - t0
    dlg_wait = wait_no_dialog()
    seen = w.stop()
    if not files:
        raise pp.Guard(f"{tag}: no new .wav under Samples/ within 120 s; windows seen {seen}")
    # LOM view of the result
    t1 = time.time()
    tr1 = tracks()
    t_lom = time.time() - t1
    extra = Counter(t["name"] for t in tr1) - Counter(names0)
    new_tracks = [t for t in tr1 if extra.get(t["name"], 0) > 0]
    new_clips = [(t["name"], c) for t in tr1 for c in t["clips"] if (t["name"], c[0], c[2]) not in clips0]
    fps = [c[3] for _, c in new_clips if c[3]]
    exist = all(os.path.exists(p) for p in fps) and bool(fps)
    res = {"tag": tag, "label": label, "t_click": round(t_click, 3), "t_first_file": round(t_first, 3),
           "t_last_growth": round(t_last, 3), "t_detect": round(t_files, 3), "dialog_wait": round(dlg_wait, 2),
           "t_lom_read": round(t_lom, 3), "windows_seen": seen, "new_tracks": [t["name"] for t in new_tracks],
           "new_clips": new_clips, "lom_file_paths_exist": exist,
           "files": {os.path.relpath(p, pp.PROJ): s for p, s in files.items()},
           "mutes_after": {t["name"]: t["mute"] for t in tr1 if t["mute"]}}
    log("e4_" + tag, t_last, **{k: v for k, v in res.items() if k not in ("new_clips", "files")},
        n_files=len(files), n_new_clips=len(new_clips))
    print("per file [first, last growth, bytes]:", {os.path.basename(p): v for p, v in PER_FILE.items()}, flush=True)
    print("new clips:", new_clips, flush=True)
    print("files:", res["files"], flush=True)
    for p in files:
        dst = OUT + f"{tag}__{os.path.basename(p)}"
        shutil.copyfile(p, dst)
        print("  ", os.path.basename(dst), wav_info(dst), flush=True)
    if expect_new_tracks is not None and len(new_tracks) != expect_new_tracks:
        print(f"NOTE {tag}: expected {expect_new_tracks} new track(s), got {len(new_tracks)}", flush=True)
    pp.check(f"{tag}: after", expect_front=NAME)
    return res


def part_bounce1():
    """First render after the fresh load: bounce with the perc group selected over 8..88."""
    pp.check("e4 bounce1: start", expect_front=NAME)
    sel = select_lane(PERC)
    time.sleep(0.5)
    labs = bounce_labels()
    print("selected:", sel, "labels:", labs, flush=True)
    to_new = [l for l in labs if "to New Track" in l]
    if len(to_new) != 1:
        raise pp.Guard(f"bounce1: no single 'to New Track' item in {labs}")
    run_menu_render("bounce1", to_new[0])


def delete_bounce_tracks(tag):
    """Q4: remove every '(Bounce)' track in one LOM call."""
    pp.check(f"{tag}: before", expect_front=NAME)
    t = time.time()
    n = A.r('''
gone = []
for i in reversed(range(len(song.tracks))):
    if song.tracks[i].name.endswith("(Bounce)"):
        gone.append(song.tracks[i].name)
        song.delete_track(i)
result = gone''')
    log("e4_" + tag, time.time() - t, deleted=n, n=len(n))
    pp.check(f"{tag}: after", expect_front=NAME)
    return n


def reactivate(tag="reactivate_clips"):
    """Bounce to New Track deactivates (clip.muted) the source clips it rendered. v01 has every clip
    active, so set all source clips active again in one LOM call."""
    pp.check(f"{tag}: before", expect_front=NAME)
    t = time.time()
    n = A.r('''
n = 0
for t in song.tracks:
    if t.is_foldable or t.name.endswith("(Bounce)"):
        continue
    for c in t.arrangement_clips:
        if c.muted:
            c.muted = False
            n += 1
result = n''')
    log("e4_" + tag, time.time() - t, reactivated=n)
    pp.check(f"{tag}: after", expect_front=NAME)
    return n


def part_reactivate():
    reactivate()


def part_clean1():
    delete_bounce_tracks("delete_bounce_tracks")


def part_bounce2():
    """Q1 single group: Select Loop, then re-select the perc group over LOM, then bounce."""
    pp.check("e4 bounce2: start", expect_front=NAME)
    select_lane(PERC)
    A.r(f'song.view.selected_track = [t for t in song.tracks if t.name == {KICK!r}][0]')
    sel = A.r(f'song.view.selected_track = [t for t in song.tracks if t.name == {PERC!r}][0]\nresult = song.view.selected_track.name')
    time.sleep(0.5)
    labs = bounce_labels()
    print("selected:", sel, "labels:", labs, flush=True)
    to_new = [l for l in labs if "to New Track" in l]
    if len(to_new) != 1:
        raise pp.Guard(f"bounce2: no single 'to New Track' item in {labs}")
    run_menu_render("bounce2", to_new[0])


def export_groups(stem, **kw):
    """Q2 reference: Export 'All Individual Tracks' over the same 8..88 selection."""
    pp.check(f"export {stem}: before", expect_front=NAME)
    t = time.time()
    written = pp.export(OUT + stem + ".wav", START, LEN, "All Individual Tracks")
    log("e4_export_all", time.time() - t, stem=stem, files=len(written), **kw)
    pp.check(f"export {stem}: after", expect_front=NAME)
    return written


def fresh_load():
    """Save NAME, open the scratch AWAY set, then reopen NAME (a real load from disk)."""
    pp.check("fresh_load: start", expect_front=NAME)
    pp.prepare_switch()
    pp.open_set(AWAY)
    pp.check("fresh_load: away", expect_front=AWAY)
    pp.prepare_switch()
    t = time.time()
    pp.open_set(NAME)
    log("e4_load", time.time() - t, set=NAME, **pp.live_footprint_gb())
    pp.check("fresh_load: back", expect_front=NAME)


def part_export_now():
    # exp_warm (first try) rendered deactivated sources: Bounce had muted the clips. Kept as evidence.
    export_groups("exp_warm2", after="bounce1 + clip reactivation, same session")


def part_export_fresh():
    fresh_load()
    export_groups("exp_fresh", after="fresh load, first render")


def part_bounce_fresh():
    """Second first-render-after-load bounce (all groups), to check bounce determinism."""
    fresh_load()
    select_lane(PERC)
    time.sleep(0.5)
    labs = bounce_labels()
    to_new = [l for l in labs if "to New Track" in l]
    if to_new != ["Bounce Groups to New Tracks"]:
        raise pp.Guard(f"bounce_fresh: expected the all-groups bounce item, labels {labs}")
    run_menu_render("bounce3", to_new[0])
    reactivate()
    delete_bounce_tracks("delete_bounce_tracks")


TARGET = "e4 paste"
PASTE_X0, PASTE_STEP = 704.0, 96.0          # past last_event_time (664): free on every track
WETS = (0.0, 0.2, 0.4, 0.6)


def source_fp():
    """Source clips (by track index, so auto-named tracks cannot fool it) in the shape's range."""
    return A.r(f'''
out = []
for i, t in enumerate(song.tracks):
    if t.is_foldable or t.name == {TARGET!r}:
        continue
    out.append([i, [(round(c.start_time, 3), round(c.end_time, 3), c.muted) for c in t.arrangement_clips if c.start_time < 100]])
result = out''')


def part_paste():
    pp.check("e4 paste: start", expect_front=NAME)
    t = time.time()
    A.r(f'''
song.create_audio_track(-1)
song.tracks[-1].name = {TARGET!r}
result = len(song.tracks)''')
    log("e4_create_target_track", time.time() - t)
    pp.check("e4 paste: target made", expect_front=NAME)
    fp0 = source_fp()
    # copy once: the Select Loop selection (all tracks, 8..88)
    t = time.time()
    select_lane(PERC)
    if not A.menu("Edit", "Copy"):
        raise pp.Guard("Edit > Copy disabled after Select Loop")
    log("e4_copy", time.time() - t, note="select_lane + Edit>Copy")
    pp.check("e4 paste: copied", expect_front=NAME)
    if not edit_enabled("Paste Bounced Audio"):
        raise pp.Guard("Paste Bounced Audio disabled right after Copy")
    for k, w in enumerate(WETS):
        x = PASTE_X0 + k * PASTE_STEP
        tp = time.time()
        pp.check(f"paste{k}: before edit", expect_front=NAME)
        t = time.time()
        got = A.r(f'''
g = [t for t in song.tracks if t.name == {PERC!r}][0]
rev = [d for d in g.devices if d.class_name == "Reverb"]
if not rev:
    g.insert_device("Reverb", len(list(g.devices)))
    rev = [d for d in g.devices if d.class_name == "Reverb"]
p = [p for p in rev[0].parameters if p.name == "Dry/Wet"][0]
p.value = p.min + {w} * (p.max - p.min)
song.view.selected_track = [t for t in song.tracks if t.name == {TARGET!r}][0]
song.current_song_time = {x}
result = [round(p.value, 4), song.view.selected_track.name, song.current_song_time]''')
        t_edit = time.time() - t
        log("e4_paste_edit", t_edit, k=k, wet=w, got=got)
        if not edit_enabled("Paste Bounced Audio"):
            raise pp.Guard(f"paste{k}: Paste Bounced Audio disabled after the edit (selected {got})")
        res = run_menu_render(f"paste{k}", "Paste Bounced Audio")
        on_target = [c for n, c in res["new_clips"] if n == TARGET]
        fp = source_fp()
        log("e4_paste_probe_total", time.time() - tp, k=k, wet=w, edit_s=round(t_edit, 3),
            paste_s=res["t_last_growth"], landed=str(on_target), new_tracks=res["new_tracks"],
            source_unchanged=fp == fp0)
        if fp != fp0:
            raise pp.Guard(f"paste{k}: source clips changed: {fp} vs {fp0}")
        if len(res["new_clips"]) != 1 or len(on_target) != 1 or abs(on_target[0][0] - x) > 1e-6 or res["new_tracks"]:
            raise pp.Guard(f"paste{k}: result not a single clip on {TARGET!r} at {x}: clips {res['new_clips']}, "
                           f"new tracks {res['new_tracks']}")


def part_del_placeholder():
    """Q4: delete clips on the target track (the paste-targeting placeholder) via track.delete_clip."""
    pp.check("del clips: before", expect_front=NAME)
    t = time.time()
    n = A.r(f'''
t = [t for t in song.tracks if t.name == {TARGET!r}][0]
cs = list(t.arrangement_clips)
for c in cs:
    t.delete_clip(c)
result = len(cs)''')
    log("e4_delete_clips", time.time() - t, n=n)
    pp.check("del clips: after", expect_front=NAME)


EDIT_PROBE = '''
# 1. undo the previous bounce's side effects: reactivate source clips, drop '(Bounce)' tracks
n_re = 0
for t in song.tracks:
    if not t.is_foldable and not t.name.endswith("(Bounce)"):
        for c in t.arrangement_clips:
            if c.muted:
                c.muted = False
                n_re += 1
gone = 0
for i in reversed(range(len(song.tracks))):
    if song.tracks[i].name.endswith("(Bounce)"):
        song.delete_track(i)
        gone += 1
# 2. the probe's parameter
g = [t for t in song.tracks if t.name == {perc!r}][0]
rev = [d for d in g.devices if d.class_name == "Reverb"]
if not rev:
    g.insert_device("Reverb", len(list(g.devices)))
    rev = [d for d in g.devices if d.class_name == "Reverb"]
p = [p for p in rev[0].parameters if p.name == "Dry/Wet"][0]
p.value = p.min + {w} * (p.max - p.min)
# 3. the range, as select_lane does
song.stop_playing()
app = Live.Application.get_application()
app.view.show_view("Arranger")
app.view.focus_view("Arranger")
song.view.selected_track = g
song.loop_start = {start}
song.loop_length = {length}
result = [round(p.value, 4), n_re, gone]'''


def part_bounce_loop():
    """Q3 substitute: per probe one LOM edit + Select Loop (x2, refreshes the menu snapshot) + Bounce."""
    pp.check("e4 bloop: start", expect_front=NAME)
    for k, w in enumerate(WETS):
        tp = time.time()
        pp.check(f"bloop{k}: before edit", expect_front=NAME)
        t = time.time()
        got = A.r(EDIT_PROBE.format(perc=PERC, w=w, start=START, length=LEN))
        t_edit = time.time() - t
        t = time.time()
        if not A.menu("Edit", "Select Loop"):
            raise pp.Guard(f"bloop{k}: Select Loop disabled")
        t_sel = time.time() - t
        log("e4_bloop_edit", t_edit, k=k, wet=w, got=got, select_s=round(t_sel, 3))

        def label():
            labs = stable_labels_for(1.0)
            to_new = [l for l in labs if "to New Track" in l]
            print(f"bloop{k} labels at click: {labs}", flush=True)
            if to_new != ["Bounce Groups to New Tracks"]:
                raise pp.Guard(f"bloop{k}: expected 'Bounce Groups to New Tracks', labels {labs}")
            return to_new[0]
        res = run_menu_render(f"bloop{k}", label)
        perc_file = [v for p, v in PER_FILE.items() if "perc group" in p and p.endswith("-1.wav")]
        log("e4_bloop_probe_total", time.time() - tp, k=k, wet=w, edit_s=round(t_edit, 3), select_s=round(t_sel, 3),
            bounce_s=res["t_last_growth"], perc_file_window=str(perc_file), new_tracks=res["new_tracks"])
        if sorted(res["new_tracks"])[-2:] != ["S01 kick group (Bounce)", "S01 perc group (Bounce)"]:
            raise pp.Guard(f"bloop{k}: unexpected new tracks {res['new_tracks']}")
    t = time.time()
    got = A.r('''
n_re = 0
for t in song.tracks:
    if not t.is_foldable and not t.name.endswith("(Bounce)"):
        for c in t.arrangement_clips:
            if c.muted:
                c.muted = False
                n_re += 1
gone = 0
for i in reversed(range(len(song.tracks))):
    if song.tracks[i].name.endswith("(Bounce)"):
        song.delete_track(i)
        gone += 1
result = [n_re, gone]''')
    log("e4_bloop_cleanup", time.time() - t, reactivated_and_deleted=got)
    pp.check("e4 bloop: end", expect_front=NAME)


# ---------------------------------------------------------------- analysis (no Live)
def load(p):
    import soundfile as sf
    x, sr = sf.read(p, dtype="float64", always_2d=True)
    return x, sr


def db(v):
    import numpy as np
    return float(20 * np.log10(max(v, 1e-300)))


def rms(x):
    import numpy as np
    return float(np.sqrt(np.mean(np.square(x))))


def best_lag(a, b, maxlag):
    """Lag L (samples) maximising sum a[n] * b[n + L] on the mono sums."""
    import numpy as np
    from scipy.signal import correlate
    am, bm = a.sum(1), b.sum(1)
    n = min(len(am), len(bm))
    c = correlate(bm[:n], am[:n], mode="full", method="fft")
    mid = n - 1
    seg = c[mid - maxlag: mid + maxlag + 1]
    k = int(np.argmax(np.abs(seg)))
    return k - maxlag


def features(x, sr, n=None):
    import numpy as np
    from scipy.signal import butter, sosfiltfilt
    x = x[:n] if n else x
    m, s = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2
    sos = butter(4, [2000, 8000], btype="band", fs=sr, output="sos")
    mb, sb = sosfiltfilt(sos, m), sosfiltfilt(sos, s)
    fr = int(0.05 * sr)
    frames = np.sqrt(np.mean(np.square(m[: len(m) // fr * fr].reshape(-1, fr)), axis=1))
    return {"rms_db": round(db(rms(x)), 2), "peak_db": round(db(float(np.max(np.abs(x)))), 2),
            "sm_2_8k_db": round(db(rms(sb)) - db(rms(mb)), 2),
            "band_2_8k_db": round(db(rms(mb)) - db(rms(m)), 2),
            "floor_p10_db": round(db(float(np.percentile(frames, 10))), 2)}


def compare(ref_path, test_path, n_ref=None, maxlag_s=0.05):
    """Align test to ref (lag within +-50 ms: the kick is periodic, a wider search locks onto a beat),
    then residual dB (raw and gain-matched) over the ref's length."""
    import numpy as np
    a, sra = load(ref_path)
    b, srb = load(test_path)
    if sra != srb:
        return {"error": f"sr {sra} vs {srb}"}
    n = n_ref or len(a)
    m0 = min(n, len(b))
    lag0 = round(db(rms(a[:m0] - b[:m0])) - db(rms(a[:m0])), 2)
    lag = best_lag(a[:n], b, int(maxlag_s * sra))
    if lag >= 0:
        aa, bb = a[:n], b[lag: lag + n]
    else:
        aa, bb = a[-lag: n], b[: n + lag]
    m = min(len(aa), len(bb))
    aa, bb = aa[:m], bb[:m]
    d = aa - bb
    g = float(np.sum(aa * bb) / max(np.sum(bb * bb), 1e-300))
    return {"lag_samples": lag, "residual_lag0_db": lag0, "len_ref": len(a), "len_test": len(b), "identical": bool(np.max(np.abs(d)) == 0.0),
            "max_abs_diff": float(np.max(np.abs(d))), "residual_db": round(db(rms(d)) - db(rms(aa)), 2),
            "gain_db": round(db(abs(g)), 3), "residual_gainmatched_db": round(db(rms(aa - g * bb)) - db(rms(aa)), 2),
            "test_tail_after_ref_db": round(db(rms(b[n + max(lag, 0):])) - db(rms(aa)), 1) if len(b) > n + max(lag, 0) else None}


def show(tag, ref, test, n_ref=None):
    import json
    a, sr = load(ref)
    b, _ = load(test)
    n = n_ref or len(a)
    row = {"pair": tag, **compare(ref, test, n_ref), "f_ref": features(a, sr, n), "f_test": features(b, sr, n)}
    print(json.dumps(row), flush=True)
    open(OUT + "compare.jsonl", "a").write(json.dumps(row) + "\n")
    return row


def first(pattern):
    import glob
    hits = sorted(glob.glob(OUT + pattern))
    return hits[0] if hits else None


def part_analyse():
    pairs = [
        ("perc: bounce1 vs export warm", "exp_warm2 S01 perc group.wav", "bounce1__Bounce S01 perc group*.wav"),
        ("kick: bounce1(first after load) vs export warm", "exp_warm2 S01 kick group.wav", "bounce1__Bounce S01 kick group*.wav"),
        ("kick: bounce1 vs export fresh(first after load)", "exp_fresh S01 kick group.wav", "bounce1__Bounce S01 kick group*.wav"),
        ("perc: bounce1 vs export fresh", "exp_fresh S01 perc group.wav", "bounce1__Bounce S01 perc group*.wav"),
        ("kick: export fresh vs export warm", "exp_fresh S01 kick group.wav", "exp_warm2 S01 kick group.wav"),
        ("perc: export fresh vs export warm", "exp_fresh S01 perc group.wav", "exp_warm2 S01 perc group.wav"),
        ("kick: bounce3(first after load) vs bounce1", "bounce1__Bounce S01 kick group*.wav", "bounce3__Bounce S01 kick group*.wav"),
        ("perc: bounce3 vs bounce1", "bounce1__Bounce S01 perc group*.wav", "bounce3__Bounce S01 perc group*.wav"),
        ("kick: bounce3 vs export fresh", "exp_fresh S01 kick group.wav", "bounce3__Bounce S01 kick group*.wav"),
    ]
    pairs += [("perc: bloop0 (Reverb 0%) vs bounce1 (no Reverb)", "bounce1__Bounce S01 perc group*.wav", "bloop0__Bounce S01 perc group*.wav"),
              ("perc: bloop0 (Reverb 0%) vs export fresh", "exp_fresh S01 perc group.wav", "bloop0__Bounce S01 perc group*.wav")]
    pairs += [(f"perc: bloop{k} (Reverb {int(w * 100)}%) vs bloop0", "bloop0__Bounce S01 perc group*.wav",
               f"bloop{k}__Bounce S01 perc group*.wav") for k, w in enumerate(WETS) if k]
    for tag, r, t in pairs:
        rp, tp = first(r), first(t)
        if rp and tp:
            show(tag, rp, tp, n_ref=1323000)      # compare the 30 s body only (bounces carry a tail)


def part_final():
    """Remove the probe Reverb, verify no bounce tracks / deactivated clips remain, save, check."""
    pp.check("e4 final: start", expect_front=NAME)
    t = time.time()
    st = A.r(f'''
g = [t for t in song.tracks if t.name == {PERC!r}][0]
for i in reversed(range(len(g.devices))):
    if g.devices[i].class_name == "Reverb":
        g.delete_device(i)
result = {{"perc_devices": [d.class_name for d in g.devices],
          "tracks": [t.name for t in song.tracks],
          "muted_clips": sum(1 for t in song.tracks if not t.is_foldable for c in t.arrangement_clips if c.muted),
          "loop": [song.loop, song.loop_start, song.loop_length]}}''')
    log("e4_final_restore", time.time() - t, **st)
    if st["muted_clips"] or any(n.endswith("(Bounce)") or n == TARGET for n in st["tracks"]) or st["perc_devices"]:
        raise pp.Guard(f"final: set not restored: {st}")
    t = time.time()
    ok = pp.save(NAME)
    log("e4_final_save", time.time() - t, wrote=str(ok))
    pp.check("e4 final: saved", expect_front=NAME)
    print("dialogs:", pp.dialogs(), "front:", A.front(), "save item enabled:",
          A.osa('tell application "System Events" to tell process "Live" to get enabled of menu item "Save Live Set" of menu "File" of menu bar 1'))


PARTS = {"final": part_final, "analyse": part_analyse, "open": part_open, "probe": part_probe, "bounce1": part_bounce1, "clean1": part_clean1,
         "bounce2": part_bounce2, "export_now": part_export_now, "export_fresh": part_export_fresh,
         "bounce_fresh": part_bounce_fresh, "reactivate": part_reactivate, "paste": part_paste, "del_placeholder": part_del_placeholder, "bounce_loop": part_bounce_loop}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for part in sys.argv[1:]:
        PARTS[part]()
