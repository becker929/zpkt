"""Plans: how the voice loop changes the music (docs/studio.md, "Making music").

A plan says which knobs of a probe kit take which values, for one section. Plans are rendered in packs (one Live
load and one export for up to P of them), every render is kept in a cache keyed by the kit's version and the
canonical plan, and two renders become one A/B file that switches every bar.

    model.py   knob ids, plans, their canonical form and cache key, the write-ahead guesses
    kits.py    a kit's metadata, version, tempo and its knobs' values and ranges (offline, from the .als)
    cache.py   the render cache: exact hits and nearest neighbours
    render.py  packing plans into kit batches, and the renderers (Live; a fake one for tests)
    abfile.py  two renders -> one loudness-matched file that alternates every bar
    cli.py     `hands plan ...`
"""
