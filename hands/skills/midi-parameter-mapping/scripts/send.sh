#!/bin/sh
# send.sh - Append a MIDI command for the running midi_vport.py daemon to emit.
# The virtual port daemon (vport.sh start) must be running, and AgentMap's Input
# must be set to AgentVirtualMIDI.
# Usage:
#   send.sh CC <channel0-15> <cc0-127> <value0-127>
#   send.sh NOTE <channel0-15> <note0-127> <velocity0-127>
#   send.sh PB <channel0-15> <value0-16383>
echo "$*" >> "${AGENTMIDI_CMD_PATH:-/tmp/agentmidi_cmds}"
