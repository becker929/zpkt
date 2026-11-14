# agent

What an agent needs to drive Ableton Live through [`hands`](../hands/) without wrecking the set.
These are plain Markdown skills with a few helper scripts. They were written for Claude Code and
work with any agent that can read a file and run a shell command.

| Skill | Use it for |
|---|---|
| [`ableton-live-control`](skills/ableton-live-control/SKILL.md) | The entry point. Two ways to reach Live (the LOM bridge behind `hands live exec`, and AbletonOSC), health checks, export, dialogs, and how to diagnose a silent render. |
| [`ableton-guide`](skills/ableton-guide/SKILL.md) | The rules that keep Live alive: what crashes it from LOM code, patterns that are not obvious, recipes for tracks, clips, devices and arrangement edits. Read it before sending code. |
| [`midi-parameter-mapping`](skills/midi-parameter-mapping/SKILL.md) | Map a MIDI CC from a controller or a virtual port to any Live or plugin parameter. |

## Use them in Claude Code

Nothing to install. `.claude/skills/` in this repo links to these folders, so opening the repo
in Claude Code loads them. To have them in every project, copy or link them into
`~/.claude/skills/`:

```bash
ln -s "$PWD/agent/skills/ableton-live-control" ~/.claude/skills/
ln -s "$PWD/agent/skills/ableton-guide" ~/.claude/skills/
```

## Use them in Gemini CLI

Nothing to install either. `.agents/skills/` links to the same folders, and `.gemini/settings.json`
makes Gemini CLI read `AGENTS.md` as its context file. Run `gemini` from the repo root (on
Anthony's Mac, `harness gemini` adds the API key from the Keychain).

The skills call `hands` by its path in this repo (`cd hands && uv run hands …`), so keep the
clone.

## The loop the skills assume

1. **Check** before acting: `hands live ping`, then `hands live check` (no dialog open, the
   expected set in front, the LOM answering).
2. **Act** in short steps: one `hands live exec` per change, never a long chain. Live runs the
   code on its main thread; a slow call freezes it.
3. **Render**: `hands live export`.
4. **Measure** the file with [`ears`](../ears/). A render that "succeeded" can still be silent.
5. **Report** the measurement, not the intent.

## Rules for agents in this repo

[`CLAUDE.md`](../CLAUDE.md) holds the repo's standing rules. The four other skills in
`.claude/skills/` (`render-plan`, `plan-cache`, `ab-1bar`, `studio-e2e`)
belong to my voice app in [`contrib/harness`](../contrib/harness/); they show how a larger
workflow is built on `hands plan`, and they assume my setup.

## Prefer MCP?

The Remote Script that `hands` talks to is from
[opendining/ableton-mcp-server](https://github.com/opendining/ableton-mcp-server), which also
ships an MCP server for the same bridge. It speaks the same protocol to the same port, so an
agent can use it instead of `hands live exec`. The bridge serves one client at a time.
