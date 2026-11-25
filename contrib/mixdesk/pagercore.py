"""The pager's decisions, apart from Live: which MiniLab control does what (a table), pages and pads, fader pickup,
loops and seeks, a control's report.

pager.py runs inside Live and loads this file by path; it imports nothing, so tests import it as it is
(tests/test_pagercore.py). Everything here takes plain values and returns plain values; the LOM stays in pager.py.
Live's Python is 3.11: keep this file free of newer syntax.
"""

PICKUP = 0.03  # a fader picks up within this distance of the value (0..1)
# The desk's set's timeline, the default of every function that needs one; another set passes its own end and loops.
END_BEAT = 160.0  # the arrangement is 40 bars at 160 BPM
DROP_BEAT = 64.0  # the build is bars 1-16, the drop starts at bar 17
LOOPS = {"build": (0.0, DROP_BEAT), "drop": (DROP_BEAT, END_BEAT - DROP_BEAT)}  # mode -> (start, length) in beats
SLOTS_V = 2  # slots A, B, W, C (v1 had B = the live mix); a reload maps a v1 "B" to "W"
PAGE_PADS = 8  # bank-A pads


# ---- the hardware: which MiniLab 3 control does what ---------------------------------------------------------------

# The faders as Live's factory MiniLab_3 script names them: CC 14, 15, 30, 31, left to right.
FADER_ELEMENTS = ("volume_fader", "send_a_fader", "send_b_fader", "pan_fader")

# One row per control the desk holds: (the factory script's element, the index in it or None for the element itself,
# its role, and what the role acts on). Roles: "knob" and "fader" drive the armed page's control on that slot (a
# fader picks up first), "toggle_pad" flips it, "page_pad" arms the page on that pad number (1-8), "page_encoder"
# steps through the pages. pager.py grabs the controls in this order. Another controller, or a layer, is another table.
HARDWARE = (
    tuple(("encoders_raw", k, "knob", f"k{k + 1}") for k in range(8))
    + tuple((name, None, "fader", f"f{k + 1}") for k, name in enumerate(FADER_ELEMENTS))
    + tuple(("pad_bank_a_raw", k, "page_pad", k + 1) for k in range(PAGE_PADS))
    + tuple(("pad_bank_b_raw", k, "toggle_pad", f"b{k + 1}") for k in range(8))
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


def page_for_encoder(value, armed, pages):
    """The page the big encoder's relative value (above 64 right, below left) steps to; None for no step."""
    step = 1 if value > 64 else -1 if value < 64 else 0
    return (armed + step) % pages if step else None


def picks_up(n, last, value, tolerance=PICKUP):
    """Does a fader at n (coming from `last`, None at first) pick up a control at `value`? Close enough, or it
    passed the value since the last report. So arming a page never makes a value jump."""
    return abs(n - value) <= tolerance or (last is not None and (last - value) * (n - value) <= 0)


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
