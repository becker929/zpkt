# lib/rig

The Live runtime the spine runs on.

- `start_headless.sh` — starts BetterDisplay and Caffeine, launches Live,
  waits for the AbletonLiveMCP port, places the window on the virtual
  display, and checks MCP control and the audio clock. A frozen clock
  means no audio device, which makes every render silent.

The failure modes it guards against are listed in
`hands/.cursor/skills/ableton-guide/SKILL.md` (silent bounces, §0 and §2).
