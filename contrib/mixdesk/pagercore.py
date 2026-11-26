"""The pager's decisions, apart from Live: which MiniLab control does what (a table), pages and pads, fader pickup,
loops and seeks, a control's report.

pager.py runs inside Live and loads this file by path; it imports nothing, so tests import it as it is
(tests/test_pagercore.py). Everything here takes plain values and returns plain values; the LOM stays in pager.py.
The app's MIDI adapter (zpkt.app.minilab) loads the same file by path and uses the same decisions; the full map of
the MiniLab (MINILAB_MAP, below) is data here too. Live's Python is 3.11: keep this file free of newer syntax.
"""

PICKUP = 0.03  # a fader picks up within this distance of the value (0..1)
# The desk's set's timeline, the default of every function that needs one; another set passes its own end and loops.
END_BEAT = 160.0  # the arrangement is 40 bars at 160 BPM
DROP_BEAT = 64.0  # the build is bars 1-16, the drop starts at bar 17
LOOPS = {"build": (0.0, DROP_BEAT), "drop": (DROP_BEAT, END_BEAT - DROP_BEAT)}  # mode -> (start, length) in beats
SLOTS_V = 2  # slots A, B, W, C (v1 had B = the live mix); a reload maps a v1 "B" to "W"
PAGE_PADS = 8  # the pads; bank A and bank B do the same (Anthony, 25 Nov 2026: pages, never pad banks)


# ---- the hardware: which MiniLab 3 control does what ---------------------------------------------------------------

# The faders as Live's factory MiniLab_3 script names them: CC 14, 15, 30, 31, left to right.
FADER_ELEMENTS = ("volume_fader", "send_a_fader", "send_b_fader", "pan_fader")

# One row per control the desk holds: (the factory script's element, the index in it or None for the element itself,
# its role, and what the role acts on). Roles: "knob" and "fader" drive the armed page's control on that slot (a
# fader picks up first), "toggle_pad" flips it, "page_pad" arms the page on that pad number (1-8), or, when the armed
# page has a compare state on that pad (compare_state), asks the app to switch to it; "page_encoder" steps through
# the pages. pager.py grabs the controls in this order. Another controller, or a layer, is another table.
HARDWARE = (
    tuple(("encoders_raw", k, "knob", f"k{k + 1}") for k in range(8))
    + tuple((name, None, "fader", f"f{k + 1}") for k, name in enumerate(FADER_ELEMENTS))
    + tuple(("pad_bank_a_raw", k, "page_pad", k + 1) for k in range(PAGE_PADS))
    + tuple(("pad_bank_b_raw", k, "page_pad", k + 1) for k in range(PAGE_PADS))
    + (("display_encoder", None, "page_encoder", None),)
)
ROLES = ("knob", "fader", "toggle_pad", "page_pad", "page_encoder")


def hardware_rows(role, table=HARDWARE):
    """The rows of `table` with that role, in order."""
    return [row for row in table if row[2] == role]


# ---- pages ---------------------------------------------------------------------------------------------------------


def pad_of(cfg, i):
    """The bank-A pad (1-8) that arms page i: its "pad", or its place among the first eight pages."""
    page = cfg["pages"][i]
    if "pad" in page:
        return int(page["pad"])
    return i + 1 if i < PAGE_PADS else None


def page_for_pad(cfg, pad, armed):
    """The page pad `pad` (1-8) arms: the first page on it, or the next one when a page on it is armed (a layer).
    None when no page is on that pad."""
    on_pad = [i for i in range(len(cfg["pages"])) if pad_of(cfg, i) == pad]
    if not on_pad:
        return None
    if armed in on_pad:
        return on_pad[(on_pad.index(armed) + 1) % len(on_pad)]
    return on_pad[0]


def step_page(armed, step, pages):
    """The page `step` places after the armed one, wrapping; None for no step."""
    return (armed + step) % pages if step else None


def page_for_encoder(value, armed, pages):
    """The page the big encoder's relative value (above 64 right, below left) steps to; None for no step."""
    return step_page(armed, 1 if value > 64 else -1 if value < 64 else 0, pages)


def picks_up(n, last, value, tolerance=PICKUP):
    """Does a fader at n (coming from `last`, None at first) pick up a control at `value`? Close enough, or it
    passed the value since the last report. So arming a page never makes a value jump."""
    return abs(n - value) <= tolerance or (last is not None and (last - value) * (n - value) <= 0)


# ---- compare states: a page's pads that switch between named settings of the same controls -------------------------

COMPARE_STEP = 0.001  # a continuous value holds a state's value within this much of its range; a switch exactly


def compare_state(cfg, page, pad):
    """The compare state (its place in the page's list) on pad `pad` (1-8) of page `page`, or None: that pad then
    arms a page as always. A page's "compare" is {"name", "pads": {"b7": 0, "b8": 1}, "states": [{"name", "writes":
    [[key, raw], ...]}], "targets": {key: its track, device and param}} (zpkt.live.page_layout.to_surfaces)."""
    if not 0 <= page < len(cfg["pages"]):
        return None
    return ((cfg["pages"][page].get("compare") or {}).get("pads") or {}).get(f"b{pad}")


def holds(value, want, lo, hi, quantized):
    """Does a control at `value` hold a state's `want`? The same rule as zpkt.live.page.holds."""
    if value is None or want is None:
        return False
    gap = abs(float(value) - float(want))
    return gap < 0.5 if quantized else gap <= (hi - lo) * COMPARE_STEP


def lit_state(states, read):
    """Which state is on: the first whose every write holds. `read(key)` gives (value, lo, hi, quantized) for a
    key, or None when the set lacks it. None when no state is on: the lit pad is derived, never stored."""
    for i, state in enumerate(states):
        writes = state.get("writes") or []
        if not writes:
            continue
        for key, want in writes:
            got = read(key)
            if got is None or not holds(got[0], want, got[1], got[2], got[3]):
                break
        else:
            return i
    return None


# ---- transport -----------------------------------------------------------------------------------------------------


def loop_mode(loop_on, start, length, loops=LOOPS):
    """The loop as the desk names it: off, build, drop, or "on" for a loop the desk did not set."""
    if not loop_on:
        return "off"
    for mode, (a, n) in loops.items():
        if abs(start - a) < 0.5 and abs(length - n) < 0.5:
            return mode
    return "on"


def seek_position(beat, end=END_BEAT):
    """Where a seek lands: inside the arrangement."""
    return max(0.0, min(end - 0.01, float(beat)))


def play_from(position, end=END_BEAT):
    """Where play starts: where the playhead is, or the top once it has run past the end."""
    return 0.0 if position >= end else position


def ran_past_end(playing, looping, beat, end=END_BEAT):
    return bool(playing) and not looping and beat >= end


def carried_slot(carry):
    """The monitor slot a reloaded pager keeps (a v1 pager's "B" was the live mix, now "W")."""
    slot = carry.get("slot", "W")
    return "W" if slot == "B" and carry.get("v") != SLOTS_V else slot


# ---- controls ------------------------------------------------------------------------------------------------------


def norm(value, lo, hi):
    """A value's place in its range, 0..1."""
    return 0.0 if hi == lo else (value - lo) / (hi - lo)


def value_at(n, lo, hi, quantized):
    """The value at place n (0..1, clamped) of a range; whole for a list or switch."""
    n = max(0.0, min(1.0, float(n)))
    v = lo + (hi - lo) * n
    return float(round(v)) if quantized else v


def toggled(value, lo, hi, quantized):
    """A pad press: a list of more than two steps through it, anything else flips between its ends."""
    if quantized and hi - lo > 1:
        return lo if value >= hi else value + 1
    return lo if value > lo else hi


def macro_position(value, a, b):
    """A macro's place (0..1) from its first parameter's value, between that parameter's "from" a and "to" b."""
    return max(0.0, min(1.0, (value - a) / (b - a))) if b != a else 0.0


def macro_value(n, a, b, lo, hi, quantized):
    """A macro part's value at place n: from a to b, whole for a list, inside the parameter's range."""
    v = a + (b - a) * n
    return max(lo, min(hi, round(v) if quantized else v))


def value_report(control):
    """A control's entry in a snapshot: n, s, q, err, r, key. `control` has norm(), text(), quantized(), raw(),
    key and error, as pager.py's targets do."""
    ok = not control.error
    return {
        "n": control.norm() if ok else None,
        "s": control.text() if ok else "",
        "q": control.quantized() if ok else False,
        "err": control.error,
        "r": control.raw() if ok else None,
        "key": control.key,
    }


def value_message(page, slot, control, sys_move):
    """The {"t": "v"} datagram for a control that moved; sys_move: the desk itself moved it (a monitor switch)."""
    return {
        "t": "v",
        "page": page,
        "slot": slot,
        "n": control.norm(),
        "s": control.text(),
        "r": control.raw(),
        "key": control.key,
        "sys": bool(sys_move),
    }


def inventory_line(track, device, param, now, lowest, highest, quantized):
    """One line of the set's inventory (surfaces.parse_inventory reads it): tab-separated, Q for a switch or list."""
    return "\t".join([track, device, param, now, lowest, highest, "Q" if quantized else ""])


# ---- the full map: every MiniLab 3 control, in two layers (DESIGN 3b) ------------------------------------------------

# The controls by the names the controller profile (lib/contracts/minilab3-profile.json) uses: k1-k8 knobs, f1-f4
# faders, a1-a8 and b1-b8 the two pad banks, the data knob (turn, push), the octave buttons, Hold, the mod strip, pitch
# bend, the keys, Shift and the transport buttons.
#
# One row per (control, layer): (control, layer, role, argument). The layers: "base"; "shift" (while Shift is held; a
# control with no row in it does what it does in base); "tempo" (ZpktMiniLabTempo's job: used instead of base when
# the desk is not driving the MiniLab; see tempo_layer_on). The roles and their arguments:
#   knob, fader, toggle_pad, page_pad    as in HARDWARE: the argument is the slot (or the pad number 1-8)
#   knob_fine                            the knob moves its control in small steps
#   page_step                            +1 or -1: the next or previous page
#   window_step                          +1 or -1: the next or previous loop window (off, build, drop)
#   focus_step, focus_reset, focus_set, focus_select, latch_compare, latch_focus, group_next, scrub, hear_hold
#   action                               a named action (ACTIONS): the argument is its name
#   tempo_fader, tempo_scale             tempo on a fader (whole BPM), or tempo times the argument
LAYERS = ("base", "shift", "tempo")
KEYS = 25  # the keys: a 25-step selector
KEYS_BASE_NOTE = 48  # the lowest key at the controller's default octave (C3), unverified (the profile says so)
SCRUB_BEATS = 4.0  # one detent of the data knob with Shift moves the playhead by a bar
BEND_ENGAGE = 0.30  # pitch bend past this (0..1 of its throw) holds Pin (up) or Ref (down) ...
BEND_RELEASE = 0.15  # ... and back inside this lets go (so a trembling strip does not flicker)
FINE_SCALE = 0.1  # a knob with Shift moves its control a tenth as far as the knob moved
TEMPO_MIN, TEMPO_MAX = 60.0, 200.0  # fader 4 as tempo (ZpktMiniLabTempo's range)

# Both pad banks do the same thing, with and without Shift: the desk uses pages, never the MiniLab's pad banks
# (Anthony, 25 Nov 2026). Switches are flipped on the screen. Pin, drop and mark have no pad: they are on the screen.
PAD_SHIFT_ACTIONS = (
    "transport.toggle",
    "hear.now",
    "hear.pin",
    "hear.ref",
    "history.undo",
    "history.redo",
    "history.checkpoint",
    "monitor.match",
)

MINILAB_MAP = (
    tuple((f"k{k}", "base", "knob", f"k{k}") for k in range(1, 9))
    + tuple((f"k{k}", "shift", "knob_fine", f"k{k}") for k in range(1, 9))
    + tuple((f"f{k}", "base", "fader", f"f{k}") for k in range(1, 5))
    + tuple((f"a{k}", "base", "page_pad", k) for k in range(1, 9))
    + tuple((f"b{k}", "base", "page_pad", k) for k in range(1, 9))
    + tuple(
        (f"{bank}{k}", "shift", "action", name) for bank in "ab" for k, name in enumerate(PAD_SHIFT_ACTIONS, start=1)
    )
    + (
        ("data_turn", "base", "focus_step", None),
        ("data_turn", "shift", "scrub", SCRUB_BEATS),
        ("data_push", "base", "focus_reset", None),
        ("data_push", "shift", "group_next", None),
        ("octave_down", "base", "page_step", -1),
        ("octave_up", "base", "page_step", 1),
        ("octave_down", "shift", "window_step", -1),
        ("octave_up", "shift", "window_step", 1),
        ("mod", "base", "focus_set", None),
        ("bend", "base", "hear_hold", ("pin", "ref")),  # up holds the first, down the second
        ("hold", "base", "latch_compare", None),
        ("hold", "shift", "latch_focus", None),
        ("keys", "base", "focus_select", KEYS),
        ("play", "base", "action", "transport.toggle"),
        ("stop", "base", "action", "transport.stop"),
        ("loop", "base", "action", "loop.cycle"),
        ("f4", "tempo", "tempo_fader", None),
        ("a7", "tempo", "tempo_scale", 0.5),
        ("a8", "tempo", "tempo_scale", 2.0),
    )
)

# Named actions the map may use, and whether the app can do them yet. "later" ones are not built; the adapter says
# so on the display and does nothing.
ACTIONS = {
    "transport.toggle": "now",
    "transport.stop": "now",
    "loop.cycle": "now",
    "hear.now": "now",
    "hear.pin": "now",
    "hear.ref": "now",
    "history.undo": "now",
    "history.redo": "now",
    "history.checkpoint": "now",
    "monitor.match": "now",
    "pin.set": "now",
    "pin.drop": "later",
    "choice.mark": "later",
}


def map_rows(control, layer, table=MINILAB_MAP):
    """The rows of `table` for a control in a layer, in order."""
    return [row for row in table if row[0] == control and row[1] == layer]


def row_for(control, shift, tempo, table=MINILAB_MAP):
    """The row that decides what a control does now: the tempo layer first (when on), then Shift's, then base."""
    layers = (["tempo"] if tempo else []) + (["shift"] if shift else []) + ["base"]
    for layer in layers:
        rows = map_rows(control, layer, table)
        if rows:
            return rows[0]
    return None


def tempo_layer_on(mode, driving):
    """Is the tempo layer used? mode "on", "off", or "auto" (when the desk is not driving the MiniLab)."""
    return mode == "on" or (mode == "auto" and not driving)


def tempo_from_fader(value):
    """The tempo (whole BPM) of a fader at 0..127."""
    return round(TEMPO_MIN + (TEMPO_MAX - TEMPO_MIN) * value / 127.0)


def tempo_scaled(bpm, factor):
    """The tempo after a pad that doubles or halves it, kept inside what Live takes."""
    return max(20.0, min(999.0, bpm * factor))


def relative_step(value):
    """A relative control's turn (64 is still, above is right, below is left) as a whole number of detents."""
    return int(value) - 64


def fine_value(n, last, value, scale=FINE_SCALE):
    """A control's place (0..1) after a knob moved from `last` to `value` (0..127) with Shift: a fraction of the move.
    The first report of a knob (last None) moves nothing."""
    if last is None:
        return n
    return max(0.0, min(1.0, n + (value - last) / 127.0 * scale))


def focus_order(slots):
    """The slots the data knob walks through: knobs, then faders, then bank-B pads, each in number order."""
    rank = {"k": 0, "f": 1, "b": 2}
    return sorted(slots, key=lambda s: (rank.get(s[:1], 3), int(s[1:]) if s[1:].isdigit() else 0))


def step_focus(order, focus, step):
    """The slot `step` places on from `focus` in `order` (wrapping); the first (or last) when nothing is focused."""
    if not order:
        return None
    if focus not in order:
        return order[0] if step > 0 else order[-1]
    return order[(order.index(focus) + step) % len(order)]


def focus_groups(order):
    """The data knob's groups: knobs, faders and bank-B pads, each as the slots of `order` it holds."""
    return [[s for s in order if s[:1] == kind] for kind in ("k", "f", "b") if any(s[:1] == kind for s in order)]


def next_group_focus(order, focus):
    """The first slot of the group after the focused one's (wrapping); the first group's first with no focus."""
    groups = focus_groups(order)
    if not groups:
        return None
    here = next((i for i, g in enumerate(groups) if focus in g), -1)
    return groups[(here + 1) % len(groups)][0]


def bend_amount(value):
    """Pitch bend (0..16383, 8192 at rest) as -1..1."""
    return max(-1.0, min(1.0, (int(value) - 8192) / 8192.0))


def bend_hold(amount, holding, up="pin", down="ref"):
    """What pitch bend holds now: `up`, `down` or None. Past BEND_ENGAGE it holds; once holding, only inside
    BEND_RELEASE of the middle lets go."""
    if amount >= BEND_ENGAGE:
        return up
    if amount <= -BEND_ENGAGE:
        return down
    if holding is not None and abs(amount) > BEND_RELEASE:
        return holding
    return None


def key_position(note, base=KEYS_BASE_NOTE, count=KEYS):
    """The place (0..1) a key selects: the lowest key is 0, the highest is 1; outside the keys, the nearest end."""
    step = max(0, min(count - 1, int(note) - base))
    return step / (count - 1)


def loop_window(mode, step, windows=("off", "build", "drop")):
    """The loop window `step` places on from `mode` (a mode the desk did not set, "on", counts as the first)."""
    here = windows.index(mode) if mode in windows else 0
    return windows[(here + step) % len(windows)]
