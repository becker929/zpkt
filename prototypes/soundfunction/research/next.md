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
- The mailbox is pull request #25 on becker929/anthonybecker.me. Set
  `MAILBOX_PR=25` in `ops/local.env` on the Mac and run `ops/mac/install.sh`
  yourself, in your own Terminal: the agent is not allowed to load launchd jobs.
- Every job has an id like `live_multitrack_bounce_v1`. The zip of results,
  its MANIFEST.md, and the write-up all carry it.
- When the Live agent hits something the spec did not foresee, it writes it
  in MANIFEST.md under "things that fought us" and carries on. That is how
  the spec gets fixed. It worked well this round.
- If a tool is missing on the Mac, the Live agent says so in the MANIFEST and
  stops. The research agent adds it to the branch.

## 3. The next Live job

`live_rumble_bypass_v1` is done (12 September): LFOTool is one broadband
duck to silence, no split. Results are on the branch under
`results/live_rumble_bypass_v1/`. The next two jobs go through the mailbox
(PR #25), not through a pasted prompt:

1. **Trim and measure the multitrack.** The 18 stems from the first bounce
   are 57% trailing silence. Trim each to its track's own content length,
   then run `lab/runner.py --local` on the folder and return the report JSON.
   No Live needed. This gives the bench sheet on true multitracks.
2. **Knob map, HW002 kick group.** Roar, Dist COLDFIRE and the Compressor on
   the kick group, one parameter at a time, whole range, 13 steps, same
   method as the SNTS clipper. About two rows per rig-day.

## 4. Things only you can do

In order of how much they unblock.

1. Run `ops/mac/install.sh` in your own Terminal so `act` messages become Reminders.
2. If the Live agent still asks for Accessibility, grant it to the terminal it runs from. It should not need it for tap bounces.
3. Do the listening test once with the new sounds. Thirty-one pairs, about
   fifteen minutes. Your three earlier answers were against the old set.
4. Make one track with a target in mind, using the clipper table: pick a
   crest, set the value, bounce it, put it in Drive. That closes the loop
   once, by hand, before the machine does it.
5. Optional: set the `LAB_TOKEN` secret on the site so the runner can post
   results without me. Not needed for anything above.
