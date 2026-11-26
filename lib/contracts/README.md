# Contracts

The JSON that crosses between the spine's parts. Each part validates its own
output against these files in its tests, so a join cannot drift silently.

| File | Producer | Consumer | Source of truth |
|---|---|---|---|
| `project-config.schema.json` | a person | `zpkt live` (`zpkt live execute --config`; once `hands`) | generated from `src/zpkt/live/models.py` by `hands/tools/gen_schemas.py` |
| `audio-profile.schema.json` | `zpkt audio analyze --json` (once `ears`) | agents and scripts reading a profile | generated from `src/zpkt/audio/models.py` by `ears/scripts/gen_schema.py` |
| `desk.schema.json` | the mix desk (`contrib/mixdesk/recipe.py write`, the recipe's `desk`) | `zpkt live state diff\|put RECIPE.json` | generated from `src/zpkt/live/desk.py` by `hands/tools/gen_schemas.py` |
| `mixdesk-message.schema.json` | the mix desk's pager (UDP datagrams) and server (server-sent events) | the desk's server and page | generated from `contrib/mixdesk/protocol.py` by `contrib/mixdesk/gen_schema.py` |
| `mixdesk-surface.schema.json` | the mix desk's "Make a surface" (`<sets_dir>/surfaces/<set>/*.json`) | the desk's server and pager | generated from `contrib/mixdesk/surfaces.py` by `contrib/mixdesk/gen_schema.py` |
| `page.schema.json` | an agent or a person asking for a page of controls (`<sets_dir>/pages/<set>/*.json`) | `zpkt live page lint` and the app (`zpkt.app`: `page.make`, `page.lint`) | generated from `src/zpkt/live/page.py` by `hands/tools/gen_schemas.py` |
| `page-layout.schema.json` | the app's `page.layout` command (`zpkt.live.page_layout`: a Page as one panel per MiniLab page, every slot of the MiniLab on it) | the /app/ shell, which draws it | generated from `src/zpkt/live/page_layout.py` by `hands/tools/gen_schemas.py` |
| `inventory.schema.json` | `zpkt live library inventory --json` | a person, agents planning work | generated from `src/zpkt/live/library/models.py` by `hands/tools/gen_schemas.py` |
| `arrangement.schema.json` | the HW002 arranger's pages (`contrib/arranger/server.py`) and the mix desk (`desk`) | the arranger's scripts (`mixset.py`, `spectral.py`, `kickfuzz.py`), the mix desk, `zpkt live state ... RECIPE.json` | written by hand to match `contrib/arranger/arrangement.py`; its tests check both agree |
| `app-api.schema.json` | the app's API (`src/zpkt/app/adapters/api.py`, `POST /api/v1/...`) and its callers (`zpkt.app.client`, `zpkt` command, booth, demo) | the app and the callers | written by hand; `tests/app/test_api_contract.py` checks the code and the file agree |
| `option.schema.json` | the app (`zpkt.app.options`: a job on the render queue, `options.get`, `GET /api/options`) | the /app/ shell, agents | written by hand to match `src/zpkt/app/options.py`; `tests/app/test_options.py` checks both agree |
| `minilab3-profile.json` (with `.schema.json`) | a person, at the MiniLab (`zpkt app midi learn`) | the app's MIDI adapter (`zpkt.app.minilab.profile`) | written by hand; every item marked unverified, and its `basis` says where it came from (Live's installed MiniLab_3 script, the MIDI standard, a guess, or unknown) |
| `live-watch.schema.json` | the Remote Script's watch (`AbletonLiveMCP`) and `zpkt.live.watch` | the app (`zpkt.app.watching`) | written by hand; `tests/live/test_watch.py` checks the messages both sides send against it |
| `song.schema.json` | the app's `song.*` commands (`zpkt.app.song`) | the `/app/` shell's Song tab, agents, the API | written by hand; `tests/app/test_song_contract.py` validates real answers against it |
| `ask-event.schema.json` | Ask (`zpkt.app.ask`): every line of a session's events file and every event of its stream | the Ask page, the notes, the failure budget | written by hand to match `src/zpkt/app/ask/events.py` and the engines; its tests check both agree |
| `ask-session.schema.json` | Ask's sessions index (`sessions.json`) | the Ask page and service | written by hand; Zpkt web's entries pass too |
| `ask-tool.schema.json` | an agent's MCP server (`zpkt.app.ask.mcp`) | `POST /app/ask/api/tool` | written by hand to match `src/zpkt/app/ask/tools.py` |
| `proposal.schema.json` | an agent's `propose_option` (`options.json` in the Ask folder) | the person, in the Options sheet (the app's one store of Options, `zpkt.app.options`) | written by hand to match `src/zpkt/app/proposals.py` |

The music bot's and booth's contracts (`score.schema.json`, `booth-*.schema.json`) moved with them to the private
repo `becker929/music-bot` (its `contracts/`) on 24 November 2026.

taste, engineer and the letta-vibe agent, which used the old `feedback` and `verdict` contracts, were removed on
24 November 2026 (git tag `pre-upgrade-2026-11-24`). `project-config` (`src/zpkt/live/models.py`) stays for now.
