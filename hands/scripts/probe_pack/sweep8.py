"""Batch 8 sweeps: find a target range in Live before an A/B batch is cut.

  cd hands && uv run python scripts/probe_pack/sweep8.py chord

A sweep is a list of patterns, each the baseline (batch 6 "all") plus a few knob settings, rendered in
one kit batch per *view*: "mix" (everything), "solo" (only the target sound) and "rest" (everything
but the target). ears/mlab/spikes/hw002_mixclimb/measure8.py reads the three and reports, per pattern,
the target's loudness (LUFS), how far it sits under the rest (LU) and per band. Patterns past the
listed ones repeat the baseline, which gives the render-to-render noise.
Writes <data_dir>/sweep8/<sweep>/<view>/pattern_XX.wav + sweep.json (data_dir: hands.config).
"""
import json
import sys

import ab_live as AB

from hands import als, config
from hands import probe_kit as PK
from hands.live.knobs import Knob
from hands.live.transport import LiveClient

CH = AB.CHORD
CF = ("plugin", "Dist COLDFIRE")
CF_ON = ("PluginDevice", 2)          # the chord's COLDFIRE (after LFOTool and Supermassive)
UT = ("StereoGain", 0)               # the chord's Utility: Gain is linear amplitude, StereoWidth a fraction
DRUMS = ("S01 kick group", "S01 perc group")


def db(x):
    return 10 ** (x / 20)


def chord_gain(dB):
    """The chord's Utility Gain (linear) for `dB` above the set's -8.33 dB."""
    return round(0.3831186891 * db(dB), 9)


SWEEPS = {
    # The chord loop sits ~21 LU under the mix (9 Oct). COLDFIRE's "Shine Bright" (Tube into
    # Transformer, configured on 9 Oct) at three drive pairs and three Colour settings; Utility
    # width (10 % in the set) and level (Utility at -8.33 dB in the set).
    "chord": {
        "kit": "c8x16", "target": CH,
        "views": {"mix": [], "solo": [(g, "Mixer", "Speaker", False) for g in DRUMS],
                  "rest": [(CH, "Mixer", "Speaker", False)]},
        "patterns": [
            ("baseline", []),
            *[(f"coldfire drive A {a:.2f} B {b:.2f}", [(CH, CF_ON, "On", True), (CH, CF, "Distortion A Drive", a),
                                                       (CH, CF, "Distortion B Drive", b)])
              for a, b in ((0.25, 0.3), (0.5, 0.65), (0.824, 1.0))],
            *[(f"coldfire colour {c:.2f}", [(CH, CF_ON, "On", True), (CH, CF, "Color", c)]) for c in (0.0, 0.5, 1.0)],
            *[(f"width {w:.0%}", [(CH, UT, "StereoWidth", w)]) for w in (0.5, 1.0, 1.5)],
            *[(f"level +{g} dB", [(CH, UT, "Gain", chord_gain(g))]) for g in (4, 8, 12)],
        ],
    },
}

# Batches 8.2-8.4 (9 Oct), cut from the chord sweep: COLDFIRE (any drive) costs 5.4 LU of chord
# loudness; width adds 0.9 / 2.7 / 4.6 LU at 50 / 100 / 150 %. Colour and width are only heard
# once the chord is up, so 8.3 and 8.4 sit on the chord at +8 dB, loudness-matched to it.
CHORD_VIEWS = {"mix": [], "solo": [(g, "Mixer", "Speaker", False) for g in DRUMS]}
COLDFIRE_MAKEUP, WIDTH_LU = 5.4, {0.5: 0.9, 1.0: 2.7, 1.5: 4.6}
BATCHES = {
    "b8_2_chord_level": {
        "kit": "c8x4", "target": CH, "views": CHORD_VIEWS,
        "patterns": [("baseline", [])] + [(f"chord +{g} dB", [(CH, UT, "Gain", chord_gain(g))]) for g in (4, 8, 12)],
    },
    "b8_3_chord_colour": {
        "kit": "c8x4", "target": CH, "views": CHORD_VIEWS,
        "patterns": [("chord +8 dB", [(CH, UT, "Gain", chord_gain(8))])] +
                    [(f"colour {c:.2f}", [(CH, CF_ON, "On", True), (CH, CF, "Color", c),
                                          (CH, UT, "Gain", chord_gain(8 + COLDFIRE_MAKEUP))]) for c in (0.5, 0.75, 1.0)],
    },
    "b8_4_chord_width": {
        "kit": "c8x4", "target": CH, "views": CHORD_VIEWS,
        "patterns": [("chord +8 dB", [(CH, UT, "Gain", chord_gain(8))])] +
                    [(f"width {w:.0%}", [(CH, UT, "StereoWidth", w), (CH, UT, "Gain", chord_gain(8 - lu))])
                     for w, lu in WIDTH_LU.items()],
    },
}
SWEEPS.update(BATCHES)

# The chord's Supermassive, "short and tight, more to change the texture and frequency" (Anthony,
# 9 Oct), on the chord at +8 dB. Short delay and low feedback in every pattern; Mix, the cuts and
# the delay move.
SM, SM_ON = ("plugin", "ValhallaSupermassive"), ("PluginDevice", 1)
UP8 = (CH, UT, "Gain", chord_gain(8))


def tight(mix, delay=0.1, low=0.0, high=1.0, fb=0.2):
    return [UP8, (CH, SM_ON, "On", True), (CH, SM, "Mix", mix), (CH, SM, "Delay_Ms", delay),
            (CH, SM, "Feedback", fb), (CH, SM, "LowCut", low), (CH, SM, "HighCut", high)]


SWEEPS["chord_sm"] = {
    "kit": "c8x16", "target": CH, "views": SWEEPS["chord"]["views"],
    "patterns": [("baseline chord +8 dB", [UP8])] +
                [(f"sm mix {m}", tight(m)) for m in (0.2, 0.4, 0.6, 0.8)] +
                [("sm mix 0.5 lowcut 0.3", tight(0.5, low=0.3)), ("sm mix 0.5 lowcut 0.5", tight(0.5, low=0.5)),
                 ("sm mix 0.5 highcut 0.5", tight(0.5, high=0.5)), ("sm mix 0.5 delay 0.05", tight(0.5, delay=0.05)),
                 ("sm mix 0.5 delay 0.2", tight(0.5, delay=0.2)), ("sm mix 0.5 feedback 0.4", tight(0.5, fb=0.4))] +
                [("baseline chord +8 dB", [UP8])] * 5,
}
# Batch 8.5: Mix across the tight range, low cut 0.3 for the frequency; makeup from the chord_sm sweep.
SM_MAKEUP = {0.3: 0.9, 0.55: 2.0, 0.8: 4.5}   # 0.8 measured 1.6 LU short at 2.9
SWEEPS["b8_5_chord_texture"] = {
    "kit": "c8x4", "target": CH, "views": CHORD_VIEWS,
    "patterns": [("chord +8 dB", [UP8])] +
                [(f"supermassive mix {m}", tight(m, low=0.3)[1:] + [(CH, UT, "Gain", chord_gain(8 + mu))])
                 for m, mu in SM_MAKEUP.items()],
}


# The break (bars 81-88, the synths): space through the Break group's Hybrid Reverb (Prism with a
# "Textures / Vocal A" convolution in parallel, Dry/Wet 50 %, Decay 3.5 s) and colour through its
# COLDFIRE (Default: Wavefolder; Drive, Colour and Mix configured on 9 Oct in kit k8x16).
BG, HY, BCF = "Break group", ("Hybrid", 0), ("plugin", "Dist COLDFIRE")
SWEEPS["break"] = {
    "kit": "k8x16", "target": BG,
    "views": {"mix": [], "solo": [(g, "Mixer", "Speaker", False) for g in DRUMS + ("SFX group",)],
              "rest": [(BG, "Mixer", "Speaker", False)]},
    "patterns": [("baseline", [])] +
                [(f"reverb dry/wet {w}", [(BG, HY, "DryWet", w)]) for w in (0.25, 0.7, 0.9)] +
                [(f"reverb decay {d} s", [(BG, HY, "Algorithm_Decay", d)]) for d in (1.5, 8.0)] +
                [(f"coldfire colour {c}", [(BG, BCF, "Color", c)]) for c in (0.3, 0.5, 1.0)] +
                [(f"coldfire drive {d}", [(BG, BCF, "Distortion A Drive", d)]) for d in (0.4, 1.0)] +
                [(f"coldfire mix {m}", [(BG, BCF, "Mix", m)]) for m in (0.0, 0.5)] +
                [("baseline", [])] * 3,
}

# Batches 8.6-8.7 from the break sweep. The break is nearly all Break group, so the -14 LUFS of each
# cut version already level-matches it.
BREAK_VIEWS = {"mix": [], "solo": SWEEPS["break"]["views"]["solo"]}
SWEEPS["b8_6_break_space"] = {
    "kit": "k8x16", "target": BG, "views": BREAK_VIEWS,
    "patterns": [("baseline", [])] + [(f"reverb dry/wet {w}", [(BG, HY, "DryWet", w)]) for w in (0.7, 0.8, 0.9)],
}
SWEEPS["b8_7_break_colour"] = {
    "kit": "k8x16", "target": BG, "views": BREAK_VIEWS,
    "patterns": [("baseline", [])] + [(f"coldfire colour {c}", [(BG, BCF, "Color", c)]) for c in (0.3, 0.5, 1.0)],
}

def plan(name):
    """Offline: the sweep's kit, labels, knobs (with the set's values) and the steps of each view."""
    sw = SWEEPS[name]
    kit = PK.Kit.load(sw["kit"])
    tree = als.load(config.rig().set_path(kit.set))
    base = AB.baseline_steps(kit.P)
    patterns = [[(Knob(tr, dev, p), v) for tr, dev, p, v in sets] for _, sets in sw["patterns"]]
    steps = PK.merge_patterns(patterns, kit.P, lambda knob: als.current_value(tree, *knob.spec),
                              taken=[knob for knob, _ in base])
    views = {view: base + steps + PK.constant({Knob(tr, dev, p): v for tr, dev, p, v in extra}, kit.P)
             for view, extra in sw["views"].items()}
    labels = [label for label, _ in sw["patterns"]] + ["baseline (repeat)"] * (kit.P - len(sw["patterns"]))
    knobs = [{"knob": knob.id, "baseline": als.current_value(tree, *knob.spec)} for knob, _ in steps]
    return kit, labels, knobs, views


def main():
    name = sys.argv[1]
    sw = SWEEPS[name]
    kit, labels, knobs, views = plan(name)
    out = config.rig().data_dir / "sweep8" / name
    client = LiveClient()
    renders = {}
    for view, steps in views.items():
        batch = PK.write_batch(kit, f"s8_{name}_{view}", steps=steps)
        man = PK.render(client, batch, kit, out / view)
        renders[view] = {k: man[k] for k in ("load_s", "export_s")}
    json.dump({"sweep": name, "kit": sw["kit"], "target": sw["target"], "labels": labels, "knobs": knobs,
               "renders": renders}, open(out / "sweep.json", "w"), indent=1)
    print(json.dumps({"sweep": name, "renders": renders}))


if __name__ == "__main__":
    main()
