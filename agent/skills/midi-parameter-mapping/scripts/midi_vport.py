#!/usr/bin/env python3
"""Persistent virtual MIDI output port for agentic control.

Opens a CoreMIDI virtual OUTPUT port named "AgentVirtualMIDI". macOS exposes
this to Ableton Live as a MIDI *input* port, hot-plugged, so Live can be told
to listen to it (assign it as AgentMap's Input port).

The daemon watches a command file and emits any new lines as MIDI. Commands:
    CC <channel0-15> <cc0-127> <value0-127>
    NOTE <channel0-15> <note0-127> <velocity0-127>
    PB <channel0-15> <value0-16383>

Run under tmux (see vport.sh) so it never wedges the agent shell.
"""
import os
import time

import rtmidi

PORT_NAME = os.environ.get("AGENTMIDI_PORT_NAME", "AgentVirtualMIDI")
CMD_PATH = os.environ.get("AGENTMIDI_CMD_PATH", "/tmp/agentmidi_cmds")


def main():
    midiout = rtmidi.MidiOut()
    midiout.open_virtual_port(PORT_NAME)
    # Truncate the command file so stale commands from a prior run are ignored.
    open(CMD_PATH, "w").close()
    pos = 0
    print(f"[agentmidi] virtual port '{PORT_NAME}' open; watching {CMD_PATH}",
          flush=True)
    try:
        while True:
            try:
                size = os.path.getsize(CMD_PATH)
            except OSError:
                size = 0
            if size < pos:  # file was truncated/rewritten
                pos = 0
            if size > pos:
                with open(CMD_PATH) as f:
                    f.seek(pos)
                    for line in f:
                        _handle(midiout, line.strip())
                    pos = f.tell()
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass
    finally:
        midiout.close_port()
        del midiout


def _handle(midiout, line):
    if not line or line.startswith("#"):
        return
    parts = line.split()
    kind = parts[0].upper()
    try:
        if kind == "CC" and len(parts) == 4:
            ch, cc, val = int(parts[1]), int(parts[2]), int(parts[3])
            midiout.send_message([0xB0 | (ch & 0x0F), cc & 0x7F, val & 0x7F])
        elif kind == "NOTE" and len(parts) == 4:
            ch, note, vel = int(parts[1]), int(parts[2]), int(parts[3])
            midiout.send_message([0x90 | (ch & 0x0F), note & 0x7F, vel & 0x7F])
        elif kind == "PB" and len(parts) == 3:
            ch, val = int(parts[1]), int(parts[2])
            midiout.send_message([0xE0 | (ch & 0x0F), val & 0x7F, (val >> 7) & 0x7F])
        else:
            print(f"[agentmidi] ignored: {line}", flush=True)
            return
        print(f"[agentmidi] sent: {line}", flush=True)
    except (ValueError, IndexError) as exc:
        print(f"[agentmidi] bad command '{line}': {exc}", flush=True)


if __name__ == "__main__":
    main()
