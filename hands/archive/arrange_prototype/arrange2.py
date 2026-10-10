"""arrange.py with a lead-in: keep the 2 source bars before the first segment.

Live's recorded take starts ~0.9 s into its own file (clip start_marker
~2.4 beats); the file's head is not on the song timeline. Rendering two
extra bars first and trimming them off keeps that junk out of the result.
uv run python arrange2.py ID '[[97,100],[105,108]]'
"""
import json
import sys

import arrange as A

LEAD = 2


def with_lead(segs):
    a0 = segs[0][0]
    lead = (max(1, a0 - LEAD), a0 - 1)
    out = [lead] if lead[1] >= lead[0] else []
    for s in segs:
        if out and s[0] == out[-1][1] + 1:
            out[-1] = (out[-1][0], s[1])
        else:
            out.append(tuple(s))
    return out, (lead[1] - lead[0] + 1 if lead[1] >= lead[0] else 0)


if __name__ == "__main__":
    vid = sys.argv[1]
    segs = [tuple(s) for s in json.loads(sys.argv[2])]
    full_segs, lead = with_lead(segs)
    res = A.make(vid, full_segs)
    res.update({"lead_bars": lead, "planned_segments": segs})
    print(json.dumps(res))
