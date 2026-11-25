# Contracts

The JSON that crosses between the spine's parts. Each part validates its own
output against these files in its tests, so a join cannot drift silently.

| File | Producer | Consumer | Source of truth |
|---|---|---|---|
| `project-config.schema.json` | a person | hands (`hands execute --config`) | generated from `src/zpkt/live/models.py` by `hands/tools/gen_schemas.py` |
| `feedback.schema.json` | none now (letta-vibe was removed) | none now | generated from `src/zpkt/live/models.py` by `hands/tools/gen_schemas.py` |
| `audio-profile.schema.json` | ears (`ears analyze --json`) | agents and scripts reading a profile | generated from `src/zpkt/audio/models.py` by `ears/scripts/gen_schema.py` |
| `desk.schema.json` | the mix desk (`contrib/mixdesk/recipe.py write`, the recipe's `desk`) | hands (`hands live state diff\|put RECIPE.json`) | generated from `src/zpkt/live/desk.py` by `hands/tools/gen_schemas.py` |
| `mixdesk-message.schema.json` | the mix desk's pager (UDP datagrams) and server (server-sent events) | the desk's server and page | generated from `contrib/mixdesk/protocol.py` by `contrib/mixdesk/gen_schema.py` |
| `mixdesk-surface.schema.json` | the mix desk's "Make a surface" (`<sets_dir>/surfaces/<set>/*.json`) | the desk's server and pager | generated from `contrib/mixdesk/surfaces.py` by `contrib/mixdesk/gen_schema.py` |
| `page.schema.json` | an agent or a person asking for a page of controls (`<sets_dir>/pages/<set>/*.json`) | hands (`hands live page lint`), later the one interface (`zpkt.app`) | generated from `src/zpkt/live/page.py` by `hands/tools/gen_schemas.py` |
| `inventory.schema.json` | hands (`hands library inventory --json`) | a person, agents planning work | generated from `src/zpkt/live/library/models.py` by `hands/tools/gen_schemas.py` |
| `arrangement.schema.json` | the HW002 arranger's pages (`contrib/arranger/server.py`) and the mix desk (`desk`) | the arranger's scripts (`mixset.py`, `spectral.py`, `kickfuzz.py`), the mix desk, hands (`hands live state ... RECIPE.json`) | written by hand to match `contrib/arranger/arrangement.py`; its tests check both agree |
| `app-api.schema.json` | the app's API (`src/zpkt/app/adapters/api.py`, `POST /api/v1/...`) and its callers (`zpkt.app.client`, `zpkt` command, booth, demo) | the app and the callers | written by hand; `tests/app/test_api_contract.py` checks the code and the file agree |
| `option.schema.json` | the app (`zpkt.app.options`: a job on the render queue, `options.get`, `GET /api/options`) | the /app/ shell, agents | written by hand to match `src/zpkt/app/options.py`; `tests/app/test_options.py` checks both agree |
| `minilab3-profile.json` (with `.schema.json`) | a person, at the MiniLab (`zpkt app midi learn`) | the app's MIDI adapter (`zpkt.app.minilab.profile`) | written by hand; every item marked unverified, and its `basis` says where it came from (Live's installed MiniLab_3 script, the MIDI standard, a guess, or unknown) |
| `live-watch.schema.json` | the Remote Script's watch (`AbletonLiveMCP`) and `zpkt.live.watch` | the app (`zpkt.app.watching`) | written by hand; `tests/live/test_watch.py` checks the messages both sides send against it |

The music bot's and booth's contracts (`score.schema.json`, `booth-*.schema.json`) moved with them to the private
repo `becker929/music-bot` (its `contracts/`) on 24 November 2026.

taste, engineer and the letta-vibe agent, which used `feedback` and the old `verdict` contract, were removed on
24 November 2026 (git tag `pre-upgrade-2026-11-24`). The models
`hands` keeps for `feedback` and `project-config` (`src/zpkt/live/models.py`) stay for now.
