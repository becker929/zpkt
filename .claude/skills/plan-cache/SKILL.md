---
name: plan-cache
description: Look up a plan in the render cache before rendering: an exact hit plays at once, and a near neighbour (knob values within about 8 percent of their ranges) can be offered while the exact one renders. Use before any render-plan or ab-1bar call when speed matters, and when Anthony asks for something close to what he already heard.
---

# plan-cache

Every render is kept by its key: the kit's version (the hash of its set) plus the canonical plan (knobs sorted,
values rounded, knobs left at the kit's value dropped). A rebuilt kit gets new keys.

```bash
cd hands && uv run --extra plans hands plan lookup PLAN
# {"key": "…", "hit": true, "audio": ".../entries/<key>/audio.wav", "plan": {...}}
# {"key": "…", "hit": false, "nearest": {"key": "…", "distance": 0.03, "audio": "…", "plan": {...}}}
# {"key": "…", "hit": false}
```

- **hit**: present it now (ab-1bar will not render anything).
- **nearest**: distance is Euclidean over the knobs, each scaled to its range (0.03 = 3% of the range). Offer it
  ("here is the closest I have, drive 48 percent, while 50 renders") and render the exact plan.
- Nothing: render (ab-1bar or render-plan).

Where it lives: `~/_agent_scratch/plans/` (`HANDS_PLANS`): `entries/<key>/{plan.json,audio.wav}`, `ab/` for the
cut A/B files. Safe to delete; it fills again.
