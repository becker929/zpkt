"""What the MiniLab is told back: the knob rings, the pad LEDs and the display. Pure: it returns SysEx by target.

A target is a name ("ring:k3", "led:a1", "display"), so the adapter can send only what changed. The colours are
plain choices, not Arturia's. None of this is checked at the hardware.
"""

from __future__ import annotations

from zpkt.app.minilab import sysex
from zpkt.app.minilab.core import pagercore
from zpkt.app.minilab.mapper import View
from zpkt.app.minilab.profile import Profile

OFF: sysex.Rgb = (0, 0, 0)
ARMED: sysex.Rgb = (127, 127, 127)  # the pad of the armed page
AVAILABLE: sysex.Rgb = (0, 0, 40)  # a pad that arms a page
ON: sysex.Rgb = (0, 127, 30)  # a switch that is on
IDLE: sysex.Rgb = (30, 8, 0)  # a switch that is off

Out = dict[str, list[int]]


def rings(profile: Profile, view: View) -> Out:
    """Each knob's ring at its control's place (0 for a knob with no control): so the knob and the value agree."""
    out: Out = {}
    for k in range(1, 9):
        slot = f"k{k}"
        control = view.controls.get(slot)
        value = round(127 * control.n) if control else 0
        out[f"ring:{slot}"] = sysex.realign(profile, profile.by_name(slot), value)
    return out


def leds(profile: Profile, view: View) -> Out:
    """Bank A shows which pages exist and which is armed; bank B shows the page's switches, lit when on. A pad that
    holds a compare state of the armed page shows that instead, on both banks: lit when its state is on."""
    core = pagercore()
    cfg = view.cfg()
    out: Out = {}
    on_pad = {core.pad_of(cfg, i) for i in range(len(view.pages))}
    armed = core.pad_of(cfg, view.page) if 0 <= view.page < len(view.pages) else None
    for pad in range(1, 9):
        colour = ARMED if pad == armed else AVAILABLE if pad in on_pad else OFF
        out[f"led:a{pad}"] = sysex.led(profile, profile.by_name(f"a{pad}"), colour)
    for pad in range(1, 9):
        control = view.controls.get(f"b{pad}")
        colour = OFF if control is None else ON if control.n >= 0.5 else IDLE
        out[f"led:b{pad}"] = sysex.led(profile, profile.by_name(f"b{pad}"), colour)
    states = view.pages[view.page].compare if 0 <= view.page < len(view.pages) else {}
    for slot in states:
        colour = ON if slot == view.lit else IDLE
        for bank in "ab":
            name = f"{bank}{slot[1:]}"
            out[f"led:{name}"] = sysex.led(profile, profile.by_name(name), colour)
    return out


def page_display(profile: Profile, view: View) -> Out:
    """The armed page's name, and its place among the pages."""
    if not view.pages or not 0 <= view.page < len(view.pages):
        return {}
    return {"display": sysex.display(profile, view.pages[view.page].name, f"page {view.page + 1} of {len(view.pages)}")}


def feedback(profile: Profile, view: View, page_changed: bool = True) -> Out:
    """Everything to send for this view. The rings and the page's name only when a page was armed: a ring sent while
    the hand is on its knob would fight it, and a name would cover what the display was showing."""
    out = leds(profile, view)
    if page_changed:
        out.update(rings(profile, view))
        out.update(page_display(profile, view))
    return out
