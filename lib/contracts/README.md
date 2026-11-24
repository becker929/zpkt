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
| `inventory.schema.json` | hands (`hands library inventory --json`) | a person, agents planning work | generated from `src/zpkt/live/library/models.py` by `hands/tools/gen_schemas.py` |
| `score.schema.json` | the music bot's composer (Claude) | the booth (`contrib/booth`) | generated from `contrib/booth/src/booth/score.py` by `contrib/booth/scripts/gen_schema.py` |
| `booth-job-request.schema.json` | the music bot (`contrib/bot/booth.mjs`, POST /v1/jobs) | the booth | generated from `contrib/booth/src/booth/contract.py` by `contrib/booth/scripts/gen_schema.py` |
| `booth-job.schema.json`, `booth-measure.schema.json`, `booth-check.schema.json`, `booth-status.schema.json`, `booth-error.schema.json` | the booth's HTTP API (jobs, `measure.json`, check, status, errors) | the music bot; its fake booth is tested against them | generated from `contrib/booth/src/booth/contract.py` by `contrib/booth/scripts/gen_schema.py` |
| `arrangement.schema.json` | the HW002 arranger's pages (`contrib/arranger/server.py`) and the mix desk (`desk`) | the arranger's scripts (`mixset.py`, `spectral.py`, `kickfuzz.py`), the mix desk, hands (`hands live state ... RECIPE.json`) | written by hand to match `contrib/arranger/arrangement.py`; its tests check both agree |

taste, engineer and the letta-vibe agent, which used `feedback` and the old `verdict` contract, were removed on
24 November 2026 (git tag `pre-upgrade-2026-11-24`). The models
`hands` keeps for `feedback` and `project-config` (`src/zpkt/live/models.py`) stay for now.
