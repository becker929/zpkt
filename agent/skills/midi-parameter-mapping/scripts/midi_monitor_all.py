#!/usr/bin/env python3
"""Log incoming MIDI from ALL input ports to a log file.

Each line is tagged with the source port name, so you can see which physical
port a controller's knobs/pads actually use and what CC/note numbers they send.
Used to discover a hardware controller's CC map before writing AgentMap config.
"""
import os
import time

import rtmidi

LOG = os.environ.get("AGENTMIDI_MONITOR_LOG", "/tmp/agentmidi_monitor.log")


def describe(msg):
    if not msg:
        return "empty"
    status = msg[0]
    hi = status & 0xF0
    ch = status & 0x0F
    if hi == 0xB0 and len(msg) >= 3:
        return f"CC   ch{ch:<2} cc={msg[1]:<3} val={msg[2]}"
    if hi == 0x90 and len(msg) >= 3:
        return f"NOTE ch{ch:<2} note={msg[1]:<3} vel={msg[2]}"
    if hi == 0x80 and len(msg) >= 3:
        return f"NOFF ch{ch:<2} note={msg[1]:<3} vel={msg[2]}"
    if hi == 0xE0 and len(msg) >= 3:
        return f"PB   ch{ch:<2} val={(msg[2] << 7) | msg[1]}"
    if hi == 0xA0 and len(msg) >= 3:
        return f"AT   ch{ch:<2} note={msg[1]:<3} val={msg[2]}"
    if hi == 0xD0 and len(msg) >= 2:
        return f"CAT  ch{ch:<2} val={msg[1]}"
    if status == 0xF0 or (msg and msg[0] == 0xF0):
        return "SYSEX " + " ".join(format(b, "02X") for b in msg)
    return "raw " + " ".join(str(b) for b in msg)


def main():
    tmp = rtmidi.MidiIn()
    port_names = tmp.get_ports()
    del tmp
    ins = []
    open(LOG, "w").close()
    with open(LOG, "a") as f:
        for i, name in enumerate(port_names):
            m = rtmidi.MidiIn()
            m.open_port(i)
            # Keep SysEx (Arturia DAW-mode handshakes use it); drop clock noise.
            m.ignore_types(sysex=False, timing=True, active_sense=True)
            ins.append((name, m))
            f.write(f"opened [{i}] {name}\n")
        f.write("--- listening on all ports ---\n")
        f.flush()
    try:
        while True:
            got = False
            for name, m in ins:
                msg = m.get_message()
                while msg:
                    data, _dt = msg
                    with open(LOG, "a") as f:
                        f.write(f"{name:<28} {describe(data)}\n")
                        f.flush()
                    got = True
                    msg = m.get_message()
            if not got:
                time.sleep(0.004)
    except KeyboardInterrupt:
        pass
    finally:
        for _name, m in ins:
            m.close_port()


if __name__ == "__main__":
    main()
