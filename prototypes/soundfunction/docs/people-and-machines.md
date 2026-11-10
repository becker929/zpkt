# People and machines

## Anthony

Producer of industrial hard techno, fifteen years. Owner of the project, the
site, the Mac, the Drive folder, and every audio file involved. GitHub
`becker929`. He is the only source of listening-test answers so far and the
only person who can pick between renders, which makes his choices the scarce
input of the whole plan.

How he likes to be worked with, from his stated preferences and his
feedback this week: brief, no preamble, no closing recap; prose over bullets
unless the content is a list; push back on weak premises; name the source
tier when it does work; never inflate a timeline, and check dates against the
record; plain language that does not "feel Claudish". He moved the mandate
to the Mac because the two-machine relay was costing more than it returned.

## The Mac

MacBook Air, macOS 26.3, arm64. Ableton Live 12 Suite. Two control paths:
OSC via AbletonOSC (UDP 11000) and the Live Object Model via an MCP bridge
(`AbletonLiveMCP`, TCP 16619). Python 3.12 venv for the lab.

Paths that matter:
- `~/sandbox/sound-function` — this repository.
- `~/sandbox/autodaw/hands/` — the `hands` package and the sweep runners;
  `sweeps/HANDOFF.md` is the previous Mac agent's log.
- `~/.agents/skills/ableton-live-control/` — the Live control skill
  (`scripts/live.py`, `scripts/live_mcp.py`, `reference/lom-guide.md`).
- `~/_tmsmsm/` — Anthony's real projects (`Active Tracks/`,
  `daw-library/experimental projects/`). Never opened directly.
- `~/_agent_scratch/` — copy-on-write clones. Disposable.
- `ops/local.env` — ntfy topic, mailbox repo and PR number, agent name.

Things that have interfered: a Hammerspoon config (fixed by Anthony mid-run
on 9 Sep), sleep and the lock screen, a permission layer that refuses
`launchctl` and `osascript` assistive access. Keep the machine awake:
`sudo pmset -c sleep 0 disksleep 0 displaysleep 0`, `caffeinate -dis`.

## The web session (retired from the loop, 12 Sep)

A Claude Code session in a remote container, "Techno Harness Research". It
built most of what is here between 5 and 12 September. It keeps a
three-hourly Routine reading PR #25 and will answer `@research` comments
while it lives. It holds nothing that is not on the branch.

## Repositories and URLs

- `becker929/anthonybecker.me` — `main` is the site; `sound-function-research`
  is this repository; PR #25 is the mailbox.
- `becker929/hammerspoon-config` — his Hammerspoon config; the web session
  was opened against it but did no work there.
- https://anthonybecker.me — the site. Notes at `/notes/<slug>/`, research
  at `/research/sound-function/`, mirror of this repo at
  `/research/sound-function/repo/`, listening test at
  `/research/sound-function/listen/`, lab at `/lab`.
- Drive folder `claude-research-2026-09-06`, id `1kyN0yo7LsarLa-4kPq5Ahv6JiGvtVWkd`.

## Channels

- ntfy topic in `ops/local.env`; three levels; the Mac mirrors `act` into
  Apple Reminders list "Techno harness" once the installer has been run.
- Mailbox PR #25: `@research`, `@mac`, `@anthony` as first line.
- Both agents post as `becker929`; tell them apart by the first line, never
  by author.
