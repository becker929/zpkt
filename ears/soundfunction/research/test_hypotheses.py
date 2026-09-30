#!/usr/bin/env python3
"""Test every hypothesis in research/hypotheses.md that the data on disk can test, and write
the results table between the markers in that file.   python3 research/test_hypotheses.py"""
import json, csv, re, sys
from pathlib import Path
import numpy as np
from scipy import stats
ROOT = Path(__file__).resolve().parent.parent
S = json.load(open(ROOT / "corpus2" / "summary.json")); T = S["tracks"]; A = S["all"]
R = {r["id"]: r for r in json.load(open(ROOT / "corpus2" / "stems_results.json"))}
E = json.load(open(ROOT / "lab" / "drive" / "reports" / "embedding.json")) if (ROOT / "lab" / "drive" / "reports" / "embedding.json").exists() else None
M = {m["id"]: m for m in json.load(open(ROOT / "corpus2" / "manifest.json"))}
res = []
def rec(hid, verdict, evidence): res.append((hid, verdict, evidence))
def arr(k, rows=T): return np.array([t[k] for t in rows if t.get(k) is not None], dtype=float)
def pair(ka, kb, rows=T):
    xs = [(t[ka], t[kb]) for t in rows if t.get(ka) is not None and t.get(kb) is not None]
    return np.array([x for x, _ in xs], float), np.array([y for _, y in xs], float)
def spear(x, y):
    r, p = stats.spearmanr(x, y); return r, p
def fmt_r(r, p, n): return f"Spearman r = {r:+.2f}, p = {p:.3g}, n = {n}"
n = len(T)

# H6 kick attacks on beats >= 2x chance
v = arr("sub_on_beats"); rec("H6", "supported" if np.median(v) >= 0.5 else "not supported", f"median share of sub attacks on the four beats {np.median(v):.2f} (chance 0.25), {int((v > 0.5).sum())}/{len(v)} above 0.5")
# H7 backbeat is a minority
cb = sum(t["clear_backbeat"] for t in T); rec("H7", "supported" if cb / n < 0.25 else "not supported", f"clear backbeat in {cb}/{n} = {cb / n:.0%}")
# H8 pump independent of tempo
x, y = pair("tempo", "pump_depth_db"); r, p = spear(x, y); rec("H8", "supported" if p > 0.05 or abs(r) < 0.15 else "not supported", fmt_r(r, p, len(x)))
# H9 backbeat tracks pump less
a = np.array([t["pump_depth_db"] for t in T if t["clear_backbeat"] and t.get("pump_depth_db") is not None]); b = np.array([t["pump_depth_db"] for t in T if not t["clear_backbeat"] and t.get("pump_depth_db") is not None])
u, p = stats.mannwhitneyu(a, b); rec("H9", "supported" if np.median(a) < np.median(b) and p < 0.05 else ("not supported" if p >= 0.05 else "reversed"), f"pump median with backbeat {np.median(a):.1f} dB (n={len(a)}) vs without {np.median(b):.1f} dB (n={len(b)}), Mann-Whitney p = {p:.3g}")
# H10 returns on 8-bar line >= 2x chance
rec("H10", "supported" if A["return_on_8_line"] >= 0.25 else "not supported", f"{A['return_on_8_line']:.0%} of kick returns on a multiple of 8 bars (chance 12.5%); 4-bar {A['return_on_4_line']:.0%} (25%); 16-bar {A['return_on_16_line']:.0%} (6.25%)")
# H11 drops >=4 bars favour multiples of 4
h = {int(k): v for k, v in A["break_len_hist"].items()}; long_ = sum(v for k, v in h.items() if k >= 4); m4 = sum(v for k, v in h.items() if k >= 4 and k % 4 == 0)
rec("H11", "supported" if m4 / max(long_, 1) >= 0.5 else "not supported", f"{m4}/{long_} = {m4 / max(long_, 1):.0%} of kick drops of 4+ bars are a multiple of 4 (chance 25%)")
# H12 kick-off share vs tempo
x, y = pair("tempo", "kick_off_share"); r, p = spear(x, y); rec("H12", "supported" if r < -0.15 and p < 0.05 else "not supported", fmt_r(r, p, len(x)))
# H13 bass-stem pump >= mix pump (part three)
ok = [r for r in R.values() if r["levels"].get("bass", -99) > -18 and r.get("sidechain") is not None and r.get("pump_mix") is not None]
d = np.array([r["sidechain"] - r["pump_mix"] for r in ok]); rec("H13", "supported" if np.median(d) > 0 else "not supported", f"bass-on-kick-onsets minus mix pump: median {np.median(d):+.1f} dB over {len(ok)} excerpts with an audible bass stem")
# H14 sidechain return scales with beat length
x = np.array([60000 / r["tempo"] for r in ok if r.get("sidechain_return")]); y = np.array([r["sidechain_return"] for r in ok if r.get("sidechain_return")]); r_, p = spear(x, y)
rec("H14", "supported" if r_ > 0.2 and p < 0.05 else "not supported", fmt_r(r_, p, len(x)) + f"; return / beat median {np.median(y / x):.2f}")
# H15 landing pitch vs tempo
x = np.array([r["tempo"] for r in R.values() if r.get("kick_pitch_hz")]); y = np.array([r["kick_pitch_hz"] for r in R.values() if r.get("kick_pitch_hz")]); r_, p = spear(x, y)
rec("H15", "supported" if p > 0.05 or abs(r_) < 0.15 else "not supported", fmt_r(r_, p, len(x)))
if E:
    C = [i for i in E["items"] if i["kind"] == "corpus"]; V = lambda k: np.array([i["values"][k] if i["values"].get(k) is not None else np.nan for i in C], float)
    br, bs = V("bass_rel_db"), V("k_sub"); kb = V("body_bright"); ring = V("k_ring_db"); pump = V("pump_mix"); dec = V("body_decay20")
    # H16 separate bass layer -> brighter kick body
    sep = br > -6; m = ~np.isnan(kb)
    u, p = stats.mannwhitneyu(kb[sep & m], kb[~sep & m]); rec("H16", "supported" if np.median(kb[sep & m]) > np.median(kb[~sep & m]) and p < 0.05 else "not supported", f"kick body brightness with a bass layer within 6 dB of the drums: median {np.median(kb[sep & m]):.0f} Hz (n={int((sep & m).sum())}) vs without {np.median(kb[~sep & m]):.0f} Hz (n={int((~sep & m).sum())}), p = {p:.3g}")
    # H17 kick left at next beat vs pump depth
    m = ~np.isnan(ring) & ~np.isnan(pump); r_, p = spear(ring[m], pump[m]); rec("H17", "supported" if r_ < -0.2 and p < 0.05 else ("reversed" if r_ > 0.2 and p < 0.05 else "not supported"), fmt_r(r_, p, int(m.sum())) + " (kick level at next beat vs pump on the mix)")
    # H26 kick body fall vs sub share (short thump = sub-carrying?)
    m = ~np.isnan(dec) & ~np.isnan(bs); r_, p = spear(dec[m], bs[m]); rec("H26", "supported" if r_ < -0.2 and p < 0.05 else "not supported", fmt_r(r_, p, int(m.sum())) + " (kick body fall time vs kick sub share)")
# H18 labels vs producers: share of variance between labels
labs = {}; 
for t in T: labs.setdefault(t.get("label") or "?", []).append(t["pump_depth_db"])
labs = {k: v for k, v in labs.items() if len(v) >= 5}
allv = np.array([x for v in labs.values() for x in v]); gm = allv.mean(); ssb = sum(len(v) * (np.mean(v) - gm) ** 2 for v in labs.values()); sst = ((allv - gm) ** 2).sum()
rec("H18", "supported" if ssb / sst >= 0.1 else "not supported", f"labels with 5+ tracks explain {ssb / sst:.0%} of the variance in pump depth ({len(labs)} labels, {len(allv)} tracks)")
# H19 tempo by year
def year_of(t):
    m = re.search(r"(20[12]\d)", str(t.get("year") or M.get(t["id"], {}).get("year") or "")); return int(m.group(1)) if m else 0
yrs = [(year_of(t), t["tempo"]) for t in T]; yrs = [(y, tp) for y, tp in yrs if 2018 <= y <= 2026]
early = np.array([tp for y, tp in yrs if y <= 2021]); late = np.array([tp for y, tp in yrs if y >= 2023]); u, p = stats.mannwhitneyu(early, late)
rec("H19", "supported" if np.median(late) > np.median(early) and p < 0.05 else "not supported", f"median tempo 2018-2021 {np.median(early):.0f} bpm (n={len(early)}) vs 2023-2026 {np.median(late):.0f} (n={len(late)}), p = {p:.3g}")
# H20 kick brightness over time
if E:
    byname = {f"{t['artist']} – {t['title']}": year_of(t) for t in T}
    yr = np.array([byname.get(i["label"], 0) for i in C]); m = (yr >= 2018) & ~np.isnan(kb)
    if m.sum() > 20:
        r_, p = spear(yr[m], kb[m]); rec("H20", "supported" if r_ > 0.15 and p < 0.05 else "not supported", fmt_r(r_, p, int(m.sum())) + " (year vs kick body brightness)")
# H21 confident downbeat -> more returns on 8
conf = [t for t in T if t["beat_one_strength"] >= 2 and t.get("returns_rel_phrase")]; unc = [t for t in T if t["beat_one_strength"] < 2 and t.get("returns_rel_phrase")]
share8 = lambda rows: (sum(1 for t in rows for r in t["returns_rel_phrase"] if r % 8 == 0), sum(len(t["returns_rel_phrase"]) for t in rows))
a8, an = share8(conf); b8, bn = share8(unc); rec("H21", "supported" if an and bn and a8 / an > b8 / bn else "not supported", f"returns on the 8-bar line: {a8}/{an} = {a8 / max(an, 1):.0%} with a confident downbeat vs {b8}/{bn} = {b8 / max(bn, 1):.0%} without")
# H22 hats off the beat
v = arr("hat_off_8ths"); rec("H22", "supported" if abs(np.median(v) - 0.5) < 0.05 else "not supported", f"median share of air attacks on off-eighths {np.median(v):.2f}")
# H23 backbeat tracks slower
a = np.array([t["tempo"] for t in T if t["clear_backbeat"]]); b = np.array([t["tempo"] for t in T if not t["clear_backbeat"]]); u, p = stats.mannwhitneyu(a, b)
rec("H23", "supported" if np.median(a) < np.median(b) and p < 0.05 else "not supported", f"tempo median with backbeat {np.median(a):.0f} vs without {np.median(b):.0f} bpm, p = {p:.3g}")
# H24 model bounded by claps/hooks (from pack eval)
pe = ROOT / "lab" / "drive" / "reports" / "pack-eval.json"
if pe.exists():
    d = json.load(open(pe)); rec("H24", "supported" if d["meter_recall"].get("clap", 1) < 0.3 else "not supported", f"meter recall on 3,465 folder-labelled one-shots: " + ", ".join(f"{k} {v:.0%}" for k, v in d["meter_recall"].items()) + f"; overall {d['meter_acc']:.0%}")
# H25 clap on 2 and 4 vs label
lab_cb = {}
for t in T: lab_cb.setdefault(t.get("label") or "?", []).append(t["clear_backbeat"])
lab_cb = {k: (sum(v), len(v)) for k, v in lab_cb.items() if len(v) >= 10}
rec("H25", "supported" if all(s / c < 0.5 for s, c in lab_cb.values()) else "not supported", "clear backbeat per label: " + ", ".join(f"{k.replace('-netlabel', '')} {s}/{c}" for k, (s, c) in lab_cb.items()))

# H30-H32 loudness
lj = ROOT / "corpus2" / "loudness.json"
if lj.exists():
    Lf = json.load(open(lj)); ids = [t["id"] for t in T if t["id"] in Lf and Lf[t["id"]]["lufs"] is not None]
    lufs = np.array([Lf[i]["lufs"] for i in ids]); crest = np.array([Lf[i]["crest_db"] for i in ids]); yr2 = np.array([year_of(next(t for t in T if t["id"] == i)) for i in ids])
    rec("H30", "supported" if -10 <= np.median(lufs) <= -6 else "not supported", f"integrated loudness of the main-groove excerpts: median {np.median(lufs):.1f} LUFS, quartiles {np.quantile(lufs, .25):.1f} / {np.quantile(lufs, .75):.1f}, n = {len(lufs)}")
    m = yr2 >= 2018; r_, p = spear(yr2[m], lufs[m]); rec("H31", "supported" if r_ >= 0.15 and p < 0.05 else "not supported", fmt_r(r_, p, int(m.sum())) + " (year vs integrated loudness)")
    r_, p = spear(yr2[m], crest[m]); rec("H32", "supported" if r_ <= -0.15 and p < 0.05 else "not supported", fmt_r(r_, p, int(m.sum())) + f" (year vs crest); crest median {np.median(crest):.1f} dB")
# H33-H44 from the advice scrape, where the data allow
if E:
    C = [i for i in E["items"] if i["kind"] == "corpus"]; V = lambda k: np.array([i["values"][k] if i["values"].get(k) is not None else np.nan for i in C], float)
    blm, bsub, bmid, bslope, bdec = V("body_lowmid"), V("body_sub"), V("body_mid"), V("body_slope"), V("body_decay20")
    if not np.all(np.isnan(blm)):
        m = ~np.isnan(blm); rec("H33", "supported" if np.median(blm[m]) >= 0.15 else "not supported", f"kick body low-mid share median {np.median(blm[m]):.3f} (n={int(m.sum())})")
        m = ~np.isnan(bmid) & ~np.isnan(bslope); r_, p = spear(bmid[m], bslope[m]); rec("H35", "supported" if r_ <= -0.2 and p < 0.05 else "not supported", fmt_r(r_, p, int(m.sum())) + " (kick body mid share vs brightness slope)")
        m = ~np.isnan(bsub); rec("H36", "supported" if np.median(bsub[m]) < 0.20 else "not supported", f"kick body sub share median {np.median(bsub[m]):.3f}, quartiles {np.quantile(bsub[m], .25):.2f} / {np.quantile(bsub[m], .75):.2f} (n={int(m.sum())})")
        m = ~np.isnan(bdec); iqr = np.quantile(bdec[m], .75) - np.quantile(bdec[m], .25); rec("H40", "supported" if iqr >= 150 else "not supported", f"kick body fall-to-20 dB inter-quartile range {iqr:.0f} ms (quartiles {np.quantile(bdec[m], .25):.0f} / {np.quantile(bdec[m], .75):.0f}; the window caps at 250)")
        bands = np.stack([V(k) for k in ("body_sub", "body_low", "body_lowmid", "body_mid", "body_high", "body_air")], 1); m = ~np.isnan(bands).any(1)
        pr = bands[m] / (bands[m].sum(1, keepdims=True) + 1e-12); ent = -(pr * np.log(pr + 1e-12)).sum(1)
        byname = {f"{t['artist']} – {t['title']}": year_of(t) for t in T}; yrs_c = np.array([byname.get(i["label"], 0) for i in C])[m]; mm = yrs_c >= 2018
        r_, p = spear(yrs_c[mm], ent[mm]); rec("H41", "supported" if r_ <= -0.15 and p < 0.05 else "not supported", fmt_r(r_, p, int(mm.sum())) + " (year vs kick-body band entropy)")
        kp = V("kick_pitch"); m = ~np.isnan(kp) & ~np.isnan(bsub)
        if m.sum() > 30:
            lo, hi = np.quantile(bsub[m], [1 / 3, 2 / 3]); sd_lo = np.std(kp[m][bsub[m] <= lo]); sd_hi = np.std(kp[m][bsub[m] >= hi])
            rec("H44", "supported" if sd_hi <= 0.7 * sd_lo else "not supported", f"landing-pitch SD: top sub-share tertile {sd_hi:.1f} Hz vs bottom {sd_lo:.1f} Hz (n={int(m.sum())})")
bp = ROOT / "corpus2" / "band_pump.json"
if bp.exists():
    B = json.load(open(bp)); ok = [r for r in B.values() if "error" not in r and r.get("bass_rel_db", -99) > -18]
    d = np.array([r["sub_pump"] - r["low_pump"] for r in ok if r.get("sub_pump") is not None and r.get("low_pump") is not None])
    rec("H34", "supported" if np.median(d) >= 3 else "not supported", f"sub-band minus low-band pump on the bass stem: median {np.median(d):+.1f} dB (n={len(d)})")
    rr = np.array([r["recovery_rise_ms"] for r in ok if r.get("recovery_rise_ms") is not None]); rec("H39", "supported" if np.median(rr) > 30 else "not supported", f"recovery rise time (10-90% of the climb back) median {np.median(rr):.0f} ms (n={len(rr)})")
    hp = np.array([r["high_pump"] for r in B.values() if "error" not in r and r.get("high_pump") is not None]); rec("H42", "supported" if np.median(hp) >= 1 else "not supported", f"high-band (6 kHz+) dip on the drum stem at the beat: median {np.median(hp):.1f} dB (n={len(hp)}; a dip this deep is the hat pattern itself, off-beat hats against an on-beat kick, so this measure cannot tell a duck from the rhythm and the verdict is weak)")
    lj = ROOT / "corpus2" / "loudness.json"
    if lj.exists():
        Lf = json.load(open(lj)); pairs = [(Lf[t]["lufs"], r["low_pump"]) for t, r in B.items() if t in Lf and Lf[t]["lufs"] is not None and "error" not in r and r.get("low_pump") is not None and r.get("bass_rel_db", -99) > -18]
        x, y = np.array([a for a, _ in pairs]), np.array([b for _, b in pairs]); r_, p = spear(x, y); rec("H38", "supported" if r_ <= -0.2 and p < 0.05 else "not supported", fmt_r(r_, p, len(x)) + " (integrated loudness vs bass-stem pump; the sign is the other way, louder masters pump slightly more)")
# H43 clap/snare attacks off the beat: mid+high attack share on off-eighth/sixteenth steps, downbeat-aligned profiles
offs = []
for t in T:
    pa = np.array(t["profile_attack"]); pa = np.roll(pa, -4 * t["beat_one"], axis=1); mh = pa[3] + pa[4]
    if mh.sum() > 0: offs.append(1 - mh[[0, 4, 8, 12]].sum() / mh.sum())
rec("H43", "supported" if np.median(offs) >= 0.4 else "not supported", f"share of mid+high attacks off the four beats: median {np.median(offs):.2f} (chance for 12 of 16 steps is 0.75; the claim was about claps, and this measure cannot separate claps from hats)")
table = "| # | verdict | evidence |\n|---|---|---|\n" + "\n".join(f"| {h} | {v} | {e} |" for h, v, e in sorted(res, key=lambda x: int(re.sub(r'\D', '', x[0])))) + f"\n\n*{n} tracks in the corpus statistics; {len(R)} separated excerpts; tested {__import__('time').strftime('%Y-%m-%d %H:%M UTC', __import__('time').gmtime())}.*"
p = ROOT / "research" / "hypotheses.md"; s = p.read_text() if p.exists() else ""
if "<!-- RESULTS -->" in s:
    s = re.sub(r"<!-- RESULTS -->.*?<!-- /RESULTS -->", "<!-- RESULTS -->\n" + table + "\n<!-- /RESULTS -->", s, flags=re.S); p.write_text(s)
else:
    (ROOT / "research" / "hypotheses-results.md").write_text(table)
print(table)
