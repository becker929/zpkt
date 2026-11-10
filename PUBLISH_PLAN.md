# zpkt publish plan (interview, 2026-11-10)

## Decisions

| Topic | Decision |
|---|---|
| Reader | Ableton Live 12 tinkerers who will install and run it |
| Voice | First person: "I built this to make my tracks"; my rig and HW002 are the worked example |
| Scope | Full refactor: code layout, names, dead code, one install story |
| License | MIT |
| Platform | macOS only, said plainly |
| Shipping | `git clone` + `uv` (no PyPI) |
| Core, supported | `hands` (Live control CLI), `ears` (analyze, mlab), agent layer (skills, rules, MCP) |
| Site-tied parts | Kept public under `contrib/`: harness, booth, voice, bot, /skrng publishing, letta-vibe |
| Prototypes | Keep `prototypes/` (audio-browser, taste, engineer, humming joins them); clean READMEs |
| Corpus | Bring your own: `ears corpus build <folder>`; loudness/peak/spectra work without one |
| Working docs | `docs/journal/`, dated, apart from reference docs (plans, interviews, hw002, inventory, handoffs, TODO) |
| History | Audit the current tree only; leave history alone |

## Target tree

```
README.md          what it is, a 10-minute first run, the seven steps
LICENSE            MIT
SECURITY.md        kept, trimmed to core services + contrib pointer
CONTRIBUTING.md    tests, uv, rules (copies of Live projects, measure the render)
hands/             core
ears/              core (mlab, soundfunction inside)
agent/             skills, CLAUDE/AGENTS rules, MCP setup for driving Live
lib/               rig, contracts, record (minus /skrng publishing)
contrib/           harness, booth, voice, bot, skrng publish, letta-vibe
prototypes/        audio-browser, taste, engineer, humming
docs/              getting-started, hands, ears, agent, workflow, sound, contracts
docs/journal/      dated working docs
```

## Work order

1. Tree audit: secrets, personal paths, emails, Keychain names, tailnet hosts. Report before changing.
2. Move files (`git mv`, history kept): contrib/, agent/, humming → prototypes/, docs/journal/.
   Settle the untracked `demo/`, `hands/frontend/`, and the stray top-level `taste/`, `engineer/`.
3. Refactor core: hardcoded paths become config/env, remove dead code and `hands/archive` from the supported surface,
   consistent CLI names, Live remote-script install step.
4. ears: `corpus build`, corpus features optional with a clear message when missing.
5. Docs rewrite: README, getting-started (install Live remote script → `hands` ping → record → `ears analyze`),
   one page per core part, agent page, contrib/prototype status lines.
6. CI green on every part; a fresh-clone dry run following only the README.
7. Branch, PR, merge.

## Still to settle as I go

- Whether `lib/` stays a name or folds into core.
- Repo description and topics on GitHub.
