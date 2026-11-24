"""State keys: one value of the mix, by name, as hands.live.state, the mix desk's pager and its history spell it.

    "Kick bus/volume"   "Kick bus/pan"   "Kick bus/mute"   "Kick bus/solo"   "Kick bus/send Space"
    "Kick bus/desk EQ/1 Gain A"   "Kick bus/EQ Eight#2/1 Gain A"   "Main/desk Glue/Threshold"

Track: the track's name, a return's without Live's letter ("Space", not "A-Space"), or "Main". Device: its name, with
"#2", "#3" for the second and third device of that name on the track, so moving unlike devices changes no key.
Param: the LOM parameter's name. This is not a knob id (hands.live.knobs), which names a device by its .als tag and
index and a parameter by its path in the .als.

A send is spelled three ways, for three places: by return name under a state's "sends" ({"Space": [...]}), as
"send Space" in a key, and as "send:Space" in a desk control's or a match plan's "param". `send_key`, `send_param`
and `send_return` move between them.

Stdlib only, Python 3.11: this file also runs inside Live (hands.live.inlive).
"""

MIXER = ("volume", "pan", "mute", "solo")
SEND_IN_KEY = "send "
SEND_IN_PARAM = "send:"


def device_label(name, nth):
    """A device's name in a key: the name, then "#2", "#3" for the second and third of that name on a track."""
    return name if nth == 1 else f"{name}#{nth}"


def device_key(track, device, param):
    """The key of a device parameter; `device` as device_label gives it."""
    return f"{track}/{device}/{param}"


def mixer_key(track, what):
    """The key of a mixer value: volume, pan, mute or solo."""
    if what not in MIXER:
        raise ValueError(f"{what!r} is not a mixer value; they are {', '.join(MIXER)}")
    return f"{track}/{what}"


def send_key(track, ret):
    """The key of a send, by the return's short name ("Kick bus/send Space")."""
    return f"{track}/{SEND_IN_KEY}{ret}"


def send_param(ret):
    """A send as a desk control's or a match plan's param ("send:Space")."""
    return SEND_IN_PARAM + ret


def send_return(text):
    """The return a send names, from "send:Space" or "send Space"; None if `text` is not a send."""
    for prefix in (SEND_IN_PARAM, SEND_IN_KEY):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return None
