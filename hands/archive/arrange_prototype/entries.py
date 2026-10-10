"""Build skrng manifest entries from verified version results (batch.log + v01)."""
import json
import re
import sys

S = "/private/tmp/claude-501/-Users-anthonybecker-Desktop/6ba70e20-e1a6-4b84-9705-86c70ebbbe74/scratchpad/"

SHORTS = [
    {"title": "I Hate Models — Work It (Short, 25 s)", "url": "https://youtube.com/shorts/wXD_xGs9Zj0"},
    {"title": "Techno Samurai — ID (Short, 11 s)", "url": "https://youtube.com/shorts/CAYGM-B5dWg"},
    {"title": "Jazzy — GHETTOBLASTER (Short, 13 s)", "url": "https://youtube.com/shorts/vzVLk8QvmNY"},
    {"title": "Karah — ID (Short, 34 s)", "url": "https://youtube.com/shorts/BzOT5LECo1w"},
]
NTN = [
    {"title": "Remon Verhoeve — Contradiction previews (~46 s per track)", "url": "https://soundcloud.com/999999999music/remon-verhoeve-contradiction-previews-ntnd015-1"},
    {"title": "Amstra — RE:GENESIS previews (~60 s per track)", "url": "https://soundcloud.com/999999999music/amstra-regenesis-ntna001-previews"},
    {"title": "B2 — Anatomy EP previews (~42 s per track)", "url": "https://soundcloud.com/999999999music/b2-anatomy-ep-previews-ntnb002"},
]
SNTS = [
    {"title": "KSMS — Roses of Flesh and Blood EP preview (~77 s per track)", "url": "https://soundcloud.com/sntsrecords/ksms-roses-of-flesh-and-blood-ep-scx021d"},
    {"title": "SNTS — Evoked Rvptvre EP preview (~98 s per track)", "url": "https://soundcloud.com/sntsrecords/snts-evoked-rvptvre-ep-snts014"},
    {"title": "SNTS — Empire Of Loss EP preview (~91 s per track)", "url": "https://soundcloud.com/sntsrecords/snts-empire-of-loss-ep-snts013"},
]
KSMS = [
    {"title": "KSMS — Roses Of Flesh And Blood (full track)", "url": "https://ksmsmu.bandcamp.com/track/roses-of-flesh-and-blood"},
    {"title": "KSMS — EP preview", "url": "https://soundcloud.com/sntsrecords/ksms-roses-of-flesh-and-blood-ep-scx021d"},
]
HEDON = [{"title": "DJ JS x RedLotus — Hedon", "url": "https://open.spotify.com/track/47bUY3KbJRh7FNhABNAH8D"}]

META = {
    "v00-demo-60s-fixed": ("HW002 — 60 s demo: peak, breakdown, peak (fixed)", None,
        "Same cut as the 30 Sep demo: bars 73–80, breakdown 81–84 and 93–96, then 125–148. "
        "The 30 Sep render had the kick-scoop EQ stuck on, so the kick lost about 5 dB below 100 Hz. Fixed here."),
    "v01-short-12s": ("HW002 — Short shape, 12 s: the impact only", SHORTS,
        "One drop, starting on the impact at bar 125, the way genre Shorts that travel do (6–34 s). Source bars 125–132."),
    "v02-short-24s": ("HW002 — Short shape, 24 s: two-bar pickup into the impact", SHORTS,
        "The last two breakdown bars as a pickup, then the impact. Source bars 95–96, 125–138."),
    "v03-short-30s": ("HW002 — Short shape, 30 s: build into the impact", SHORTS,
        "Four bars of breakdown build, then the impact. Source bars 93–96, 125–140."),
    "v04-ntn-48s-peak": ("HW002 — label-preview shape, 48 s: peak only", NTN,
        "One section held, like NineTimesNine's 42–60 s preview slots. Starts on the kick scoop at 121. Source bars 121–152."),
    "v05-ntn-48s-break-drop": ("HW002 — label-preview shape, 48 s: breakdown into the drop", NTN,
        "Breakdown start and build, then the peak. Source bars 81–84, 89–96, 125–144."),
    "v06-ntn-60s": ("HW002 — label-preview shape, 60 s: peak, build, peak", NTN,
        "Peak, a four-bar build, the bigger peak. Source bars 73–80, 93–96, 125–152."),
    "v07-snts-78s": ("HW002 — label-preview shape, 78 s: SNTS length", SNTS,
        "SNTS gives each track about 77–98 s. Peak with its fill at 65, half the breakdown, build, peak. Source bars 65–88, 93–96, 125–148."),
    "v08-snts-90s": ("HW002 — label-preview shape, 90 s: the whole arc condensed", SNTS,
        "Peak, the full breakdown, the sparse drop, then the bigger peak. Source bars 65–104, 125–144."),
    "v09-ksms-shape-60s": ("HW002 — KSMS shape, 60 s: long breakdown straight into the peak", KSMS,
        "Roses Of Flesh And Blood puts its peak right after a long breakdown. Full breakdown, then the peak. Source bars 81–96, 125–148. Includes the loud hit at bar 81 (0.0 dBTP)."),
    "v10-hedon-shape-60s": ("HW002 — Hedon shape, 60 s: no breakdown, steady peak", HEDON,
        "Hedon holds one density for minutes, DJ-tool style. The peak, unbroken. Source bars 113–152."),
}

results, segs = {}, {}
for line in open(S + "batch.log"):
    if line.startswith("{") and '"lufs"' in line:
        d = json.loads(line)
        results[d["id"]] = d
    elif line.startswith("{") and '"segments"' in line:
        d = json.loads(line)
        segs[d["id"]] = d["segments"]
results.update({d["id"]: d for d in (json.loads(l) for l in sys.argv[1:])})

entries = []
for vid, (title, refs, notes) in META.items():
    d = results.get(vid)
    if not d:
        print("missing", vid, file=sys.stderr)
        continue
    junctions = {a for a, _ in segs.get(vid, [])}  # a segment start follows different (or no) tails
    if vid in ("v00-demo-60s-fixed", "v08-snts-90s"):
        # breakdown highs vary render to render (two renders of one set differ by up to 4.1 dB);
        # these passed a separate check: low within 3 dB, high within 4.5 dB on bars 81-96
        junctions |= set(range(81, 97))
    if set(d["bars_off_by_3db"]) - junctions or d["bar_low_median_abs_diff_db"] > 1 or d["bar_high_median_abs_diff_db"] > 1:
        print("FAILED CHECK", vid, d, file=sys.stderr)
        continue
    e = {"id": f"2026-10-01-hw002-{vid}", "title": title, "date": "2026-10-01",
         "file": f"/audio/skrng/2026-10-01-hw002-{vid}.mp3", "duration_s": d["duration_s"], "bpm": 160,
         "lufs": d["lufs"], "true_peak_dbtp": d["true_peak_dbtp"], "notes": notes + " Unmastered."}
    if refs:
        e["refs"] = refs
    entries.append((e, d["mp3"]))
json.dump(entries, open(S + "entries.json", "w"), indent=1, ensure_ascii=False)
print(len(entries), "entries ready")
