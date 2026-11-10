# lib/rig

Brings Live up on a headless Mac. I run zpkt on a Mac mini with no screen attached; this is the
script that makes that dependable. On a laptop with Live already open you do not need it.

- `start_headless.sh` — starts BetterDisplay and Caffeine, launches Live,
  waits for the AbletonLiveMCP port, places the window on the virtual
  display, and checks MCP control and the audio clock. A frozen clock
  means no audio device, which makes every render silent. Live's output
  is whatever is available (an external interface if connected, else the
  built-in output); renders work on either.

The failure modes it guards against are listed in
`agent/skills/ableton-guide/SKILL.md` (silent bounces, §0 and §2).
