"""The desk's live meter: a Max for Live audio effect on Main that measures what Live plays, inside Live.

    hands/.venv/bin/python contrib/mixdesk/meter.py make       # write the device into Live's User Library
    hands/.venv/bin/python contrib/mixdesk/meter.py install    # ... and load it last on Main (once)
    hands/.venv/bin/python contrib/mixdesk/meter.py listen     # print what it sends (a check)

The device ("zpkt desk meter") passes the audio through untouched. Beside it, the mid signal goes through a fixed
filter bank (Max's fffb~: 31 bands, a third of an octave each, 20 Hz to 20 kHz), each band's RMS is read 10 times a
second, and the 31 levels go to 127.0.0.1:METER_PORT as one OSC message "/spec f f ...". The server turns them into
dB and streams them to the page, which draws them over the rendered curves. Measuring only: no sound is made or
changed outside Live (contrib/docs/sound.md).

It is written from Live's own "Max Audio Effect" template (the .amxd header and its plugin~ -> plugout~ pair), with the
meter's objects added.
"""
from __future__ import annotations

import json
import socket
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "zpkt desk meter"
METER_PORT = 8987
BANDS = 31
BASE_HZ = 20.0
RATIO = 2 ** (1 / 3)
Q = 4.32                    # a third-octave band's Q
RMS_SAMPLES = 4410          # average~ window, about 0.1 s at 44.1 kHz
INTERVAL_MS = 100
TEMPLATE = Path("/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Misc/Max Devices/Max Audio Effect.amxd")
USER_LIB = Path("~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect").expanduser()


def centers() -> list[float]:
    return [BASE_HZ * RATIO ** k for k in range(BANDS)]


def _read(path: Path) -> dict:
    b = path.read_bytes()
    return json.loads(b[b.index(b"{"):].rstrip(b"\x00").decode("utf-8"))


def _write(patch: dict, path: Path) -> None:
    body = json.dumps(patch, indent=1).encode("utf-8") + b"\x00"
    head = b"ampf" + struct.pack("<I", 4) + b"aaaa" + b"meta" + struct.pack("<I", 4) + b"\x00\x00\x00\x00"
    path.write_bytes(head + b"ptch" + struct.pack("<I", len(body)) + body)


def build() -> dict:
    patch = _read(TEMPLATE)
    p = patch["patcher"]
    boxes, lines = p["boxes"], p["lines"]
    ids = {b["box"].get("text"): b["box"]["id"] for b in boxes if b["box"].get("maxclass") == "newobj"}
    pin = ids["plugin~"]
    n = [0]

    def box(text: str, ins: int, outs: list[str], x: float, y: float, w: float = 80.0) -> str:
        n[0] += 1
        oid = f"meter-{n[0]}"
        boxes.append({"box": {"id": oid, "maxclass": "newobj", "text": text, "numinlets": ins, "numoutlets": len(outs),
                              "outlettype": outs, "patching_rect": [x, y, w, 22.0]}})
        return oid

    def wire(a: str, ao: int, b: str, bi: int) -> None:
        lines.append({"patchline": {"source": [a, ao], "destination": [b, bi]}})

    x0, y0 = 420.0, 40.0
    mid = box("+~", 2, ["signal"], x0, y0)
    half = box("*~ 0.5", 2, ["signal"], x0, y0 + 30)
    bank = box(f"fffb~ {BANDS} {BASE_HZ} {RATIO:.6f} {Q}", 1, ["signal"] * BANDS, x0, y0 + 60, 260)
    ready = box("live.thisdevice", 1, ["bang", "int", "int"], x0 + 300, y0)
    metro = box(f"metro {INTERVAL_MS}", 2, ["bang"], x0 + 300, y0 + 30)
    trig = box("t " + " ".join(["b"] * BANDS), 1, ["bang"] * BANDS, x0 + 300, y0 + 60, 260)
    pack = box("pack " + " ".join(["0."] * BANDS), BANDS, [""], x0, y0 + 220, 260)
    addr = box("prepend /spec", 1, [""], x0, y0 + 250)
    send = box(f"udpsend 127.0.0.1 {METER_PORT}", 1, [], x0, y0 + 280, 160)
    wire(pin, 0, mid, 0)
    wire(pin, 1, mid, 1)
    wire(mid, 0, half, 0)
    wire(half, 0, bank, 0)
    wire(ready, 0, metro, 0)
    wire(metro, 0, trig, 0)
    for k in range(BANDS):
        avg = box(f"average~ {RMS_SAMPLES} rms", 1, ["signal"], x0 + k * 14, y0 + 100 + (k % 2) * 30, 110)
        snap = box("snapshot~", 2, ["float"], x0 + k * 14, y0 + 160 + (k % 2) * 30, 70)
        wire(bank, k, avg, 0)
        wire(avg, 0, snap, 0)
        wire(trig, k, snap, 0)          # t fires right to left: band 0 (pack's hot inlet) last
        wire(snap, 0, pack, k)
    wire(pack, 0, addr, 0)
    wire(addr, 0, send, 0)
    p["description"] = "zpkt mix desk: measures Main in third-octave bands and sends them to the desk. Audio passes through."
    return patch


def make() -> Path:
    USER_LIB.mkdir(parents=True, exist_ok=True)
    out = USER_LIB / f"{NAME}.amxd"
    _write(build(), out)
    return out


def parse(data: bytes) -> list[float] | None:
    """An OSC "/spec f f ..." message -> its floats (None for anything else)."""
    if not data.startswith(b"/spec\x00"):
        return None
    i = 8                                   # "/spec" padded to 8 bytes
    end = data.index(b"\x00", i)
    tags = data[i + 1:end].decode()
    i = (end + 4) & ~3
    vals = []
    for t in tags:
        if t == "f":
            vals.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
        elif t == "i":
            vals.append(float(struct.unpack(">i", data[i:i + 4])[0])); i += 4
        else:
            return None
    return vals


def install() -> None:
    """Load the device last on Main through the Live browser (once: does nothing if Main has it)."""
    from hands.live.transport import LiveClient
    live = LiveClient(timeout=15.0, retries=1)
    if NAME in live.run("result = [d.name for d in song.master_track.devices]"):
        print("Main already has", NAME)
        return
    path = make()
    print("wrote", path)
    code = f"""
def find(item, depth=0):
    if item.name in ({NAME!r}, {NAME + '.amxd'!r}) and item.is_loadable:
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
    for _ in range(20):                     # Live indexes a new file in the User Library within a few seconds
        if live.run(code):
            break
        time.sleep(1.5)
    else:
        sys.exit("STOP: Live's browser does not show the meter in the User Library yet; run install again")
    time.sleep(1.0)
    print("Main:", live.run("result = [d.name for d in song.master_track.devices]"))


def listen(seconds: float = 3.0) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", METER_PORT))
    s.settimeout(seconds)
    try:
        data, _ = s.recvfrom(4096)
    except socket.timeout:
        sys.exit(f"nothing on {METER_PORT} in {seconds} s")
    vals = parse(data)
    print(len(vals or []), "bands", [round(v, 5) for v in (vals or [])][:8], "...")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"make": lambda: print(make()), "install": install, "listen": listen}.get(cmd, lambda: sys.exit(__doc__))()
