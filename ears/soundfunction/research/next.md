# What to do next

Written 11 September 2026. Short on purpose.

## 1. Keep the Mac awake, by default

The rig lost one bounce to sleep and one to the lock screen. Make awake the
default, not something a script has to fight for.

- Plug into power. Leave the lid open.
- System Settings, Lock Screen: "Turn display off on power adapter" set to
  Never. "Require password after screen saver begins" set to Never, or as long
  as it allows, while runs are going.
- System Settings, Displays, Advanced: "Prevent automatic sleeping on power
  adapter when the display is off" on.
- One durable command, once: `sudo pmset -c sleep 0 disksleep 0 displaysleep 0`
- Belt and braces: open a Terminal window, run `caffeinate -dis`, and leave
  it. The Live agent should also wrap every long run in `caffeinate -dis`,
  which it already started doing.
- Leave Live open on the clone. Do not quit it between runs.

## 2. How the two agents work together

Two agents, two machines. The measurements run where the audio already is.

- The Live agent (on the Mac) drives Live AND runs the lab. It has the same
  analysis code as the research agent, cloned from the `sound-function-research`
  branch, and returns numbers: JSON, CSV, a MANIFEST.md. How to set that up
  and which tool answers which question is in `research/mac-lab.md`.
- The research agent (the web session) writes job specs and tools, reads the
  numbers, keeps the register and the site. It does not hold your audio. If
  it needs to hear something it asks for a clip: at most 30 s, at most 20 MB,
  never a whole track by default.
- Specs and tools go out through the branch: `git pull` on the Mac brings
  whatever the research agent added. Numbers come back through Drive, or
  pasted here when small.
- Every job has an id like `live_multitrack_bounce_v1`. The zip of results,
  its MANIFEST.md, and the write-up all carry it.
- When the Live agent hits something the spec did not foresee, it writes it
  in MANIFEST.md under "things that fought us" and carries on. That is how
  the spec gets fixed. It worked well this round.
- If a tool is missing on the Mac, the Live agent says so in the MANIFEST and
  stops. The research agent adds it to the branch.

## 3. The next Live job, ready to paste

This is the one that turns every published pump number from a floor into a
value, and settles the split-duck question for your track exactly.

```
First, set up the lab if it is not there yet: follow
https://anthonybecker.me/research/sound-function/repo/research/mac-lab.md
(clone the sound-function-research branch, venv, pip install -r
requirements.txt, run the six feature tests).

Then bounce HW002_14 track 3 ("rumble") twice from the same clone, same
arrangement, same length: once exactly as it is, and once with ONLY the
LFOTool device bypassed (device on = 0). Change nothing else. Name them
03__rumble.wav and 03__rumble__lfotool-off.wav, each with a sidecar, and this
time record LFOTool's parameter values in the sidecar, not just its name, so
we can see whether it shapes volume or a filter. Wrap the run in
caffeinate -dis.

Then run the analysis locally, on the Mac, and send only the JSON:
  python3 lab/duck_calibration.py calibrate --kick stems/hw002/02__kick.wav --out duck_calibrate.json
  python3 lab/duck_calibration.py bypass --kick stems/hw002/02__kick.wav \
      --bass stems/hw002/03__rumble.wav --bypass stems/hw002/03__rumble__lfotool-off.wav \
      --out duck_bypass.json

Pack the two JSON files, the two sidecars and a MANIFEST.md (same style as
last time) as live_rumble_bypass_v1.zip. Do not include the wavs. Leave the
zip on the Mac for Anthony.
```

## 4. Things only you can do

In order of how much they unblock.

1. Paste the job above into the Live agent. About an hour of rig time, plus a one-time lab setup of ten minutes.
2. Send me the resulting zip. It is small now, numbers only, so a link or a paste both work.
3. Do the listening test once with the new sounds. Thirty-one pairs, about
   fifteen minutes. Your three earlier answers were against the old set.
4. Make one track with a target in mind, using the clipper table: pick a
   crest, set the value, bounce it, put it in Drive. That closes the loop
   once, by hand, before the machine does it.
5. Optional: set the `LAB_TOKEN` secret on the site so the runner can post
   results without me. Not needed for anything above.
