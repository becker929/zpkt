# hands.testing: a fake Live for tests

I drive Live from zpkt by sending Python code strings to the AbletonLiveMCP Remote Script inside it. `FakeLive` runs
those same strings offline. It loads its own copy of `src/zpkt/live/remote_scripts/AbletonLiveMCP` and runs that script's
dispatch, eval-then-exec and serialize unchanged, over a fake Live Object Model. So a test sees what Live would
answer, and a refactor can show it sends the same calls as before.

## Use it in a test

```python
from hands.live import state
from hands.testing import FakeLive, fake_set, hw002_like


def test_take(tmp_path):
    with FakeLive(hw002_like()) as live:  # an McpTransport: pass it wherever hands takes a client
        st = state.take(live)
        assert st["tracks"]["Kick bus"]["mixer"]["volume"] == ["0.0 dB", 0.85]
        assert len(live.calls) == 7  # every call: code, seconds, status, readbacks
        assert not any(c.readbacks for c in live.calls)  # nothing read back in the call that wrote it
```

- `fake_set({...})` builds a set from a dict: tracks (audio, MIDI, group), returns, Main, devices, clips, routing
  (`sets.py` has the shape). `hw002_like()` is the mix desk's shape: six buses with "desk EQ", "desk Sat" and
  "desk Glue", returns A-Space (Reverb) and B-Echo (Echo), Main with "desk Glue", "desk Utility" and
  "desk headroom", the monitor tracks "mon A" to "mon C4". Its values are neutral and made up.
- `live.serve()` puts the script's own TCP server on a free port and returns it. Point a subprocess or a server at
  it with `--port PORT` or `ZPKT_LIVE_PORT=PORT` (the rig's `live_port`). It refuses Live's own 16619.
- `live.fail_on(n, error)`, `live.time_out_on(n, runs=True)`, `live.lose_reply_on(n, runs=True)` make call n go
  wrong the ways Live's can, with the script's own replies.
- `FakeLive(song, surfaces=[MiniLab_3()])` adds a fake MiniLab 3 for `contrib/mixdesk/pager.py`. A test plays a
  control with `minilab.elements.encoders_raw[0].receive(64)` and runs what the pager deferred with `live.tick()`.
  A pad and a knob take back what Live 12's own MiniLab_3 script sends them: `pad.send_value(red, green, blue)` is
  the LED's SysEx message (`pad.colour`, `pad.lit`), and `knob.realign_value()` takes no value (`knob.sent` has the
  values a script realigned it to).
  `live.play_for(beats)` moves a playing song's playhead.
- To change the fake set directly while it is serving, hold `live.main_thread()`.

## What it does like Live

- Expressions are evaluated, statements executed and `result` returned; errors carry the traceback, and the warning
  for code of several lines. The scope is the script's: `song`, `tracks`, `returns`, `master`, `browser`, `Live`,
  `find_item`, `load_to` and the rest.
- `str(parameter)` and `str_for_value` give Live's text: "0.0 dB" and "-inf dB" on the mixer, "C", "25L" for pan,
  "-14.8 dB", "1.14 kHz", "0.71", "On" on devices. EQ Eight, Utility, Glue Compressor, Compressor, Reverb and
  Limiter have the parameter names and order of a real dump; Saturator, Echo, Spectrum, Operator and Simpler are
  smaller.
- Listeners (`add_<prop>_listener` and the rest) fire when a value changes. A write from inside a listener raises
  "Changes cannot be triggered by notifications", and an error in a listener goes to `live.listener_errors`.
- Collections are snapshots, so a `tracks` alias goes stale after a track is made. Return names carry their letter.
  Selecting a MIDI track arms it. `song.undo()` takes back the last call. The browser loads a built-in device onto
  the selected track.

## What it does not do

- No sound, meters, rendering, recording or audio clock. The playhead moves only when a test calls `play_for`.
- Session view clips (zpkt works in the arrangement), automation envelopes, and most plug-in behaviour. A Drum
  Rack has its 128 pads with their note, name and chains (`"chains": [{"name": "Kick", "note": 36}]`), and no more:
  nothing can be loaded onto a pad.
- Live's fader law and some units are not published. Where the fake guesses, `display.py` and `devices.py` say
  GUESS. Tests should depend only on text that zpkt itself parses, not on those guesses.
- The code runs in the test's process. Modules it puts in `sys.modules` by hand are removed by `close()`.

## Tests

```bash
uv run --all-extras pytest -q -p no:cacheprovider tests/live/test_fakelive*.py
```

`test_fakelive.py` checks the fake against the Remote Script (its `serialize`, loaded by path), `test_fakelive_hands.py`
runs hands' state, knobs and panel code against it (and `hands live state` in a subprocess), and
`test_fakelive_pager.py` loads the mix desk's pager into it.
