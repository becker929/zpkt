"""The MiniLab 3 as the app sees it: the controller profile, the map from controls to commands, and the sound-free
feedback (display, LEDs, knob rings) it gets back.

    profile.py   every control and its MIDI message, read from lib/contracts/minilab3-profile.json
    sysex.py     the display, LED and knob-ring messages (pure)
    mapper.py    a control's move -> what to ask of the app (pure; the decisions are pagercore's)
    ports.py     the MIDI port: mido and rtmidi, and a fake for tests
    latency.py   the knob-to-Live timings the later rig gate reads

The adapter that runs it is zpkt.app.adapters.midi. It is off unless you ask for it (`zpkt app --adapters web,midi`).
"""
