"""Listen: a Max for Live audio effect on Main that sends what Live plays to this Mac as PCM, while asked.

    .venv/bin/python contrib/mixdesk/listen.py make       # write the device into Live's User Library
    .venv/bin/python contrib/mixdesk/listen.py install    # ... and load it last on Main (once)
    .venv/bin/python contrib/mixdesk/listen.py check      # record 5 s to a WAV; print peak, RMS and packet jitter
    .venv/bin/python contrib/mixdesk/listen.py make --debug [--port N] [--control N]   # a build that reports on UDP 8991

The device ("zpkt listen") passes the audio through untouched. Beside it, the stereo signal goes into jit.catch~,
which is emptied every INTERVAL_MS (one audio buffer of Live's at a time, as a matrix of float32), and jit.net.send sends each matrix
to 127.0.0.1:LISTEN_PORT over TCP. It sends only while asked: "/listen 1" on UDP CONTROL_PORT starts the clock that
empties jit.catch~, "/listen 0" stops it, and a watchdog stops it when no "/listen 1" has come for WATCHDOG_MS. The
reading side is zpkt.live.listen. No sound is made or changed (contrib/docs/sound.md): the stream is Live's own
output, played as it is.

Like the meter, it is written from Live's own "Max Audio Effect" template (the .amxd header and its
plugin~ -> plugout~ pair), with the listen objects added.
"""

from __future__ import annotations

import math
import socket
import sys
import tempfile
import time
import wave
from array import array
from pathlib import Path

from meter import TEMPLATE, USER_LIB, _read, _write
from zpkt.live.listen import (
    CHANNELS,
    CONTROL_PORT,
    INTERVAL_MS,
    LISTEN_PORT,
    SAMPLE_WIDTH,
    WATCHDOG_MS,
    ListenSource,
)

NAME = "zpkt listen"
BUFFER_MS = 500  # jit.catch~'s buffer: a late clock tick loses nothing until it is this late


def build(debug: bool = False, port: int = LISTEN_PORT, control: int = CONTROL_PORT) -> dict:
    patch = _read(TEMPLATE)
    p = patch["patcher"]
    boxes, lines = p["boxes"], p["lines"]
    ids = {b["box"].get("text"): b["box"]["id"] for b in boxes if b["box"].get("maxclass") == "newobj"}
    pin = ids["plugin~"]
    n = [0]

    def box(text: str, ins: int, outs: list[str], x: float, y: float, w: float = 110.0) -> str:
        n[0] += 1
        oid = f"listen-{n[0]}"
        boxes.append(
            {
                "box": {
                    "id": oid,
                    "maxclass": "newobj",
                    "text": text,
                    "numinlets": ins,
                    "numoutlets": len(outs),
                    "outlettype": outs,
                    "patching_rect": [x, y, w, 22.0],
                }
            }
        )
        return oid

    def wire(a: str, ao: int, b: str, bi: int) -> None:
        lines.append({"patchline": {"source": [a, ao], "destination": [b, bi]}})

    x0, y0 = 420.0, 40.0
    # The audio's way out: plugin~ -> jit.catch~ -> jit.net.send. Nothing here leads back to plugout~.
    catch = box(f"jit.catch~ {CHANNELS} @mode 0", CHANNELS, ["jit_matrix", ""], x0, y0 + 240, 140)
    send = box(f"jit.net.send @ip 127.0.0.1 @port {port}", 2, [""], x0, y0 + 280, 240)
    wire(pin, 0, catch, 0)
    wire(pin, 1, catch, 1)
    wire(catch, 0, send, 0)
    # The switch: "/listen 1" starts the clock and re-arms the watchdog, "/listen 0" or the watchdog stops it.
    ctl = box(f"udpreceive {control}", 1, [""], x0, y0, 130)
    route = box("route /listen", 1, ["", ""], x0, y0 + 30)
    split = box("sel 1 0", 3, ["bang", "bang", ""], x0, y0 + 60)
    keep = box("t b b b 1", 1, ["bang", "bang", "bang", "int"], x0, y0 + 90)
    off = box("t 0 stop", 1, ["int", "stop"], x0 + 160, y0 + 90)
    dog = box(f"delay {WATCHDOG_MS}", 2, ["bang"], x0 + 160, y0 + 120)
    state = box("change", 1, ["", "int", "int"], x0, y0 + 150)
    clock = box(f"qmetro {INTERVAL_MS}", 2, ["bang"], x0, y0 + 180)
    ready = box("live.thisdevice", 1, ["bang", "int", "int"], x0 + 300, y0)
    size = box(f"prepend bufsize {BUFFER_MS}", 1, [""], x0 + 300, y0 + 30, 130)
    wire(ctl, 0, route, 0)
    wire(route, 0, split, 0)
    wire(split, 0, keep, 0)
    wire(split, 1, off, 0)
    wire(keep, 3, state, 0)  # t fires right to left: clock on, watchdog armed, connection checked, rate said
    wire(keep, 2, dog, 0)
    wire(off, 1, dog, 0)
    wire(off, 0, state, 0)
    wire(dog, 0, off, 0)
    wire(state, 0, clock, 0)
    wire(clock, 0, catch, 0)
    wire(ready, 0, size, 0)
    wire(size, 0, catch, 0)
    # jit.net.send does not always find a reader that started (or came back) later. With every "/listen 1" it is
    # asked whether it is connected, and told its port again when it is not: that makes it connect.
    asked = box("t getconnected", 1, ["getconnected"], x0 + 300, y0 + 180)
    answer = box("route connected", 1, ["", ""], x0 + 300, y0 + 310)
    lost = box("sel 0", 2, ["bang", ""], x0 + 300, y0 + 340)
    tell = box(f"t {port}", 1, ["int"], x0 + 300, y0 + 370)
    again = box("prepend port", 1, [""], x0 + 300, y0 + 400)
    wire(keep, 1, asked, 0)
    wire(asked, 0, send, 0)
    wire(send, 0, answer, 0)
    wire(answer, 0, lost, 0)
    wire(lost, 0, tell, 0)
    wire(tell, 0, again, 0)
    wire(again, 0, send, 0)
    # Live's sample rate, said on the same connection with every "/listen 1" (about once a second).
    rate = box("dspstate~", 1, ["int", "float", "int", "int"], x0 + 160, y0 + 180)
    name = box("prepend sr", 1, [""], x0 + 160, y0 + 210)
    wire(keep, 0, rate, 0)
    wire(rate, 1, name, 0)
    wire(name, 0, send, 1)
    if debug:  # for finding out what the objects do inside Live: everything they say goes to UDP 8991
        tap = box("udpsend 127.0.0.1 8991", 1, [], x0 + 500, y0 + 400, 160)
        for k, (src, out) in enumerate([(send, 0), (catch, 0), (ctl, 0), (catch, 1)]):
            tag = box(f"prepend /dbg{k}", 1, [""], x0 + 500 + k * 90, y0 + 360)
            wire(src, out, tag, 0)
            wire(tag, 0, tap, 0)
        beat = box("metro 500", 2, ["bang"], x0 + 700, y0 + 30)
        beatname = box("prepend /beat", 1, [""], x0 + 700, y0 + 60)
        wire(ready, 0, beat, 0)
        wire(beat, 0, beatname, 0)
        wire(beatname, 0, tap, 0)
        # "/click" puts one full-scale sample into the stream (never into plugout~): the latency check times it.
        cmd = box("route /send /catch /click", 1, ["", "", "", ""], x0 + 500, y0 + 30, 150)
        click = box("click~", 2, ["signal"], x0 + 500, y0 + 60)
        wire(ctl, 0, cmd, 0)
        wire(cmd, 0, send, 0)
        wire(cmd, 1, catch, 0)
        wire(cmd, 2, click, 0)
        wire(click, 0, catch, 0)
    p["description"] = (
        "zpkt Listen: sends this device's input to the zpkt app as PCM while asked. Audio passes through."
    )
    return patch


def _flag(name: str, default: int) -> int:
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def make() -> Path:
    USER_LIB.mkdir(parents=True, exist_ok=True)
    out = USER_LIB / f"{NAME}.amxd"
    _write(build("--debug" in sys.argv, _flag("--port", LISTEN_PORT), _flag("--control", CONTROL_PORT)), out)
    return out


def install() -> None:
    """Load the device last on Main through the Live browser (once: does nothing if Main has it). Through the app."""
    from zpkt.live.transport import LiveClient

    live = LiveClient.via_app("cli")
    if NAME in live.run("result = [d.name for d in song.master_track.devices]"):
        print("Main already has", NAME)
        return
    path = make()
    print("wrote", path)
    code = f"""
def find(item, depth=0):
    if item.name in ({NAME!r}, {NAME + ".amxd"!r}) and item.is_loadable:
        return item
    if depth < 6 and item.is_folder:
        for c in item.children:
            hit = find(c, depth + 1)
            if hit is not None:
                return hit
    return None
b = Live.Application.get_application().browser
hit = find(b.user_library)
if hit is not None:
    song.view.selected_track = song.master_track
    devs = list(song.master_track.devices)
    if devs:
        song.view.select_device(devs[-1])
    b.load_item(hit)
result = hit is not None"""
    for _ in range(20):  # Live indexes a new file in the User Library within a few seconds
        if live.run(code):
            break
        time.sleep(1.5)
    else:
        sys.exit("STOP: Live's browser does not show the device in the User Library yet; run install again")
    time.sleep(1.0)
    print("Main:", live.run("result = [d.name for d in song.master_track.devices]"))


def open_source(port: int = LISTEN_PORT, control_port: int = CONTROL_PORT) -> ListenSource:
    """A ListenSource on its two localhost sockets (the library never opens one itself)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", port))
    except OSError as exc:
        sys.exit(f"127.0.0.1:{port} is taken ({exc}): something else is listening to Live; stop it first")
    server.listen(1)
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return ListenSource(server, control, ("127.0.0.1", control_port))


def check(seconds: float = 5.0) -> Path:
    """Record `seconds` of what the device sends to a WAV in a temp folder; print peak, RMS and packet jitter."""
    source = open_source()
    source.start()
    pcm = bytearray()
    started = time.monotonic()
    first = None
    try:
        while time.monotonic() - started < seconds + 3.0:
            chunk = source.read(0.5)
            if chunk and first is None:
                first = time.monotonic()
            pcm += chunk
            if first is not None and time.monotonic() - first >= seconds:
                break
        st = source.status()
    finally:
        source.stop()
    if not pcm:
        sys.exit(f'nothing from the device in {seconds + 3.0:.0f} s (status: {st.state}). Is "{NAME}" on Main?')
    out = Path(tempfile.mkdtemp(prefix="zpkt-listen-")) / "listen-check.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(st.rate)
        w.writeframes(bytes(pcm))
    samples = array("h")
    samples.frombytes(bytes(pcm))
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(abs(v) for v in samples) / 32768.0
    rms = math.sqrt(sum(v * v for v in samples) / len(samples)) / 32768.0

    def db(v: float) -> str:
        return f"{20 * math.log10(v):.1f} dBFS" if v > 0 else "-inf dBFS"

    heard = (time.monotonic() if first is None else first) - started
    print(out)
    print(f"status {st.state}; rate {st.rate} Hz{'' if st.rate_known else ' (assumed: the device did not say)'}")
    print(
        f"{st.frames} frames in {st.blocks} packets ({st.frames / st.rate:.2f} s of audio), {st.dropped} dropped, {st.stale} old ones skipped at the start"
    )
    print(f"peak {db(peak)}, RMS {db(rms)}")
    print(
        f"packets every {st.interval_ms:.2f} ms on average, jitter (sd) {st.jitter_ms:.2f} ms, "
        f"longest wait {st.max_gap_ms:.1f} ms; first audio {heard * 1000:.0f} ms after start"
    )
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "make":
        print(make())
    elif cmd == "install":
        install()
    elif cmd == "check":
        check()
    else:
        sys.exit(__doc__)
