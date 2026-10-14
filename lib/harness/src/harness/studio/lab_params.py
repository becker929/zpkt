"""`harness lab-params`: HW002's 100 most salient parameters, for the lab's surfaces (static/lab/data/params.json).

The list is chosen here, by hand, from what the HW002 experiments touched and what the workflow's steps are about
(docs/workflow.md: collage, arrange, kick, mix; docs/hw002/*; hands/docs/probe-packing-findings.md). Each value in
the set is read from the Live set itself, so the lab's "set" mark is what Live has. Ranges and findings come from
the experiments (batches 4-8, the b6 climbs).

Knob ids follow hands (`track|Tag:index|param`, `track|plugin:Name|param`, `track|Mixer|Volume`). A device inside a
drum rack or a clip property has no hands id; those say where they are (`kick|Drum Rack > VEC2 ... 052|...`) and are
marked `nested`. Arrangement choices have no knob (`live: null`) and say which decision they come from.
"""

from __future__ import annotations

import gzip
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .lab_audio import SET

OUT = Path(__file__).parent / "static" / "lab" / "data" / "params.json"
CHORD = "12-2022-06-02-001 [2026-05-25 092256]"
ARC = "10-ARC RAIDERS - Bastion Encounter"
SYNTH = "15-2023-11-14_bodhi-anthony-tech-01_9_stems_sound 4_ synth"
REC = "17-2023-10-07-09-20"
BEATBOX = "18-beatbox"
SPLASH = "6-2022-05-30-005"
DECAP_STYLES = ["A (Ampex)", "E (EMI)", "N (Neve)", "T (Thermionic)", "P (Pentode)"]


@dataclass
class P:
    id: str
    stage: str
    group: str
    label: str
    unit: str = ""
    scale: str = "lin"
    min: float = 0.0
    max: float = 1.0
    at: tuple | None = None          # where in the set: (track, device, param) for read()
    conv: str = "raw"                # how the set's raw value becomes the unit
    set: float | None = None         # the value when there is nothing to read (arrangement choices)
    tried: list | None = None
    note: str | None = None
    sketch: list | str | None = None
    short: str | None = None
    options: list | None = None
    step: float | None = None
    live: str | None = None
    nested: bool = False
    src: str | None = None           # read from this set instead (COLDFIRE shows a knob only once its window was opened)
    extra: dict = field(default_factory=dict)


def plan() -> list[P]:
    k, r, kg = "kick", "rumble", "kick group"
    L: list[P] = []
    add = L.append

    # ---- KICK (step IV): the kick and rumble chain: scoop, distortion, compression -------------------------
    add(P("kick.scoop", "kick", "Scoop", "Scoop (126 Hz cut)", scale="toggle", at=(k, "Eq8:0", "Bands.3/ParameterA/IsOn"),
          conv="bool", short="Scoop", sketch="kick.scoop",
          note="Automated on for the 4 bars the Short opens on. Scoops mark structure (bars 43-45 and 121-123)."))
    add(P("kick.scoopFreq", "kick", "Scoop", "Scoop cutoff", "Hz", "log", 20, 400, at=(k, "Eq8:0", "Bands.3/ParameterA/Freq"),
          tried=[57, 126.4], short="Scoop Hz", sketch="kick.scoopFreq",
          note="48 dB/oct low cut. The deep-sub climb moved it to 57 Hz; in the Short that would turn the scoop into a sub cut."))
    add(P("kick.drive", "kick", "Distortion", "COLDFIRE drive (kick bus)", "%", "lin", 0, 100,
          at=(kg, "plugin:Dist COLDFIRE", "Distortion A Drive"), conv="pct", tried=[37, 50], short="COLDFIRE",
          sketch=["ch.kick.drive@norm", "kick.drive@norm"],
          note="Batch 8.1 target 37-50% (with the rumble's Decapitator). In the set it adds low weight, not 1-3 kHz bite."))
    add(P("rumble.drive", "kick", "Distortion", "Decapitator drive (rumble)", "%", "lin", 0, 100,
          at=(r, "plugin:Decapitator", "Drive"), conv="pct", tried=[37, 50], short="Decap drive",
          sketch=["kick.rumbleDrive@norm"],
          note="7.1: 37% and 50% were best, 77% and 100% worse. About +0.7 LU per 10%."))
    add(P("rumble.style", "kick", "Distortion", "Decapitator style", scale="enum", options=DECAP_STYLES,
          at=(r, "plugin:Decapitator", "Style"), conv="enum5", short="Style", sketch="kick.rumbleStyle",
          note="Five saturation models. The b6 climb moved it with no win."))
    add(P("rumble.tone", "kick", "Distortion", "Decapitator tone", "%", "lin", 0, 100, at=(r, "plugin:Decapitator", "Tone"),
          conv="pct", short="Tone", sketch="kick.rumbleTone@norm"))
    add(P("rumble.punish", "kick", "Distortion", "Decapitator punish", scale="toggle", at=(r, "plugin:Decapitator", "Punish"),
          conv="bool", short="Punish", sketch="kick.rumblePunish", note="+20 dB into the saturator."))
    add(P("rumble.mix", "kick", "Distortion", "Decapitator mix", "%", "lin", 0, 100, at=(r, "plugin:Decapitator", "Mix"),
          conv="pct", short="Decap mix", sketch="kick.rumbleMix@norm"))
    add(P("kick.roar", "kick", "Distortion", "Roar on the kick bus", scale="toggle", at=(kg, "Roar:0", "On"), conv="bool",
          short="Roar", sketch="kick.roar",
          note="Off in the set. On, sub share drops 0.90 to 0.77; its drive is worth 2.3 dB of crest."))
    add(P("kick.l052", "kick", "Layers", "Clubby 052 layer", "dB", "lin", -36, 6, live="kick|Drum Rack > VEC2 Bassdrums Clubby 052|StereoGain|Gain",
          at=(k, "branch:VEC2 Bassdrums Clubby 052", "StereoGain/Gain"), conv="lin2db", nested=True, short="052",
          sketch="kick.layerA", note="The main hit: Simpler, EQ, COLDFIRE, Transient Shaper, Utility."))
    add(P("kick.l060", "kick", "Layers", "Clubby 060 layer", "dB", "lin", -36, 6, live="kick|Drum Rack > VEC2 Bassdrums Clubby 060|Simpler|Volume",
          at=(k, "branch:VEC2 Bassdrums Clubby 060", "Volume"), conv="raw", nested=True, short="060", sketch="kick.layerB"))
    add(P("kick.offbeat", "kick", "Layers", "Offbeat layer", "dB", "lin", -36, 6, live="kick|Drum Rack > offbeat|StereoGain|Gain",
          at=(k, "branch:offbeat", "StereoGain/Gain"), conv="lin2db", nested=True, short="Offbeat", sketch="kick.offbeat"))
    add(P("kick.attack", "kick", "Transient", "Transient attack", "%", "lin", 0, 100,
          live="kick|Drum Rack > VEC2 Bassdrums Clubby 052|plugin:kHs Transient Shaper|Attack",
          at=(k, "branch:VEC2 Bassdrums Clubby 052", "plugin:kHs Transient Shaper/Attack"), conv="pct", nested=True,
          short="Attack", sketch="kick.attack@norm",
          note="On a reference kick, attack 50-90% moved crest 8.8 to 15.5 dB and thinned the sub."))
    add(P("kick.pump", "kick", "Transient", "Transient pump", "%", "lin", 0, 100,
          live="kick|Drum Rack > VEC2 Bassdrums Clubby 052|plugin:kHs Transient Shaper|Pump",
          at=(k, "branch:VEC2 Bassdrums Clubby 052", "plugin:kHs Transient Shaper/Pump"), conv="pct", nested=True,
          short="Pump", sketch="kick.pump@norm"))
    add(P("kick.sustain", "kick", "Transient", "Transient sustain", "%", "lin", -100, 100,
          live="kick|Drum Rack > VEC2 Bassdrums Clubby 052|plugin:kHs Transient Shaper|Sustain",
          at=(k, "branch:VEC2 Bassdrums Clubby 052", "plugin:kHs Transient Shaper/Sustain"), conv="bipct", nested=True,
          short="Sustain", sketch="kick.sustain@norm"))
    add(P("kick.verb", "kick", "Transient", "Kick FlexVerb wet", "%", "lin", 0, 100,
          live="kick|Drum Rack > Drum Rack|plugin:SSL Native FlexVerb|Dry:Wet",
          at=(k, "branch:Drum Rack", "plugin:SSL Native FlexVerb/Dry:Wet"), conv="pct", nested=True, short="Verb",
          sketch="kick.verb@norm"))
    add(P("kick.sub30", "kick", "Kick bus EQ", "Deep sub (30 Hz shelf)", "dB", "lin", -15, 15,
          at=(kg, "Eq8:0", "Bands.0/ParameterA/Gain"), tried=[-14.75, 4.75], short="30 Hz", sketch="ch.kick.lowGain",
          note="The references sit 7-9 dB above HW002 at 25-40 Hz. The deep-sub climb's best: +4.75 dB."))
    add(P("kick.sub35", "kick", "Kick bus EQ", "Sub shelf (35 Hz, second EQ)", "dB", "lin", -15, 15,
          at=(kg, "Eq8:1", "Bands.0/ParameterA/Gain"), tried=[-4.34, 0.21], short="35 Hz", sketch="kick.sub35"))
    add(P("kick.body", "kick", "Kick bus EQ", "Body (62 Hz)", "dB", "lin", -15, 15, at=(kg, "Eq8:0", "Bands.1/ParameterA/Gain"),
          short="62 Hz", sketch="ch.kick.b1Gain"))
    add(P("kick.push", "kick", "Kick bus EQ", "Push into COLDFIRE (330 Hz)", "dB", "lin", -15, 15,
          at=(kg, "Eq8:0", "Bands.2/ParameterA/Gain"), short="330 Hz", sketch="ch.kick.b2Gain",
          note="Before the distortion: an untested lever for the 1.6 kHz bite that won offline (batch 5)."))
    add(P("kick.colourFreq", "kick", "Kick bus EQ", "Colour frequency", "Hz", "log", 200, 6000,
          at=(kg, "Eq8:1", "Bands.2/ParameterA/Freq"), tried=[484, 2184], short="Colour Hz", sketch="ch.kick.b3Freq",
          note="Colour climb: 484 Hz to 2.2 kHz. In the drop the gap is the 2 kHz band, 6.1 dB under the references."))
    add(P("kick.colour", "kick", "Kick bus EQ", "Colour boost", "dB", "lin", -15, 15, at=(kg, "Eq8:1", "Bands.2/ParameterA/Gain"),
          tried=[5.83, 7.58], short="Colour", sketch="ch.kick.b3Gain"))
    add(P("kick.air", "kick", "Kick bus EQ", "High shelf (5 kHz)", "dB", "lin", -15, 15, at=(kg, "Eq8:1", "Bands.3/ParameterA/Gain"),
          tried=[-11.57, -0.12], short="5 kHz", sketch="ch.kick.highGain",
          note="HW002 has about +5 dB of air near 10 kHz over the references. The colour climb took this to -11.6 dB."))
    add(P("kick.thresh", "kick", "Kick bus compressor", "Threshold", "dB", "lin", -40, 0, at=(kg, "Compressor2:0", "Threshold"),
          conv="lin2db", tried=[-8, -5.47], short="Thresh", sketch="ch.kick.compThreshold",
          note="Idle as set: the bus RMS (-9.3 dB) sits under it. Threshold is the one live knob: 11 dB of crest span."))
    add(P("kick.ratio", "kick", "Kick bus compressor", "Ratio", ":1", "log", 1, 20, at=(kg, "Compressor2:0", "Ratio"),
          tried=[1.5, 12], short="Ratio", sketch="ch.kick.compRatio"))
    add(P("kick.cattack", "kick", "Kick bus compressor", "Attack", "ms", "log", 0.01, 300, at=(kg, "Compressor2:0", "Attack"),
          tried=[0.05, 30], short="Attack", sketch="ch.kick.compAttack"))
    add(P("kick.release", "kick", "Kick bus compressor", "Release", "ms", "log", 1, 3000, at=(kg, "Compressor2:0", "Release"),
          tried=[1, 300], short="Release", sketch="ch.kick.compRelease"))
    add(P("kick.cmix", "kick", "Kick bus compressor", "Dry/wet", "%", "lin", 0, 100, at=(kg, "Compressor2:0", "DryWet"), conv="pct",
          tried=[20, 100], short="Comp mix", sketch="ch.kick.compMix@norm",
          note="Drop power: harder settings raised the mix's crest 7.9 to 13.9 dB. Offline, 36% parallel won."))
    add(P("rumble.pitch", "kick", "Rumble", "Rumble pitch (Shifter)", "st", "lin", -12, 12, at=(r, "Shifter:0", "Pitch_Coarse"),
          step=1, short="Pitch", sketch="kick.rumblePitch"))
    add(P("rumble.sub", "kick", "Rumble", "Rumble sub (31 Hz shelf)", "dB", "lin", -15, 15, at=(r, "Eq8:0", "Bands.0/ParameterA/Gain"),
          tried=[-14.26, 2.98], short="Sub", sketch="kick.rumbleSub", note="Deep-sub climb: -14.3 to +3.0 dB."))
    add(P("rumble.air", "kick", "Rumble", "Rumble high shelf (5 kHz)", "dB", "lin", -15, 15, at=(r, "Eq8:0", "Bands.3/ParameterA/Gain"),
          tried=[-6.82, 0], short="5 kHz", sketch="kick.rumbleAir"))
    add(P("rumble.mono", "kick", "Rumble", "Rumble bass mono", scale="toggle", at=(r, "StereoGain:0", "BassMono"), conv="bool",
          short="Bass mono", sketch="kick.rumbleMono", note="Mono-low climb: on (with the Main's bass mono)."))
    add(P("rumble.width", "kick", "Rumble", "Rumble width", "%", "lin", 0, 200, at=(r, "StereoGain:0", "StereoWidth"),
          conv="pct", tried=[87.7, 95.8], short="Width", sketch="kick.rumbleWidth@norm"))
    add(P("rumble.level", "kick", "Rumble", "Rumble level", "dB", "lin", -36, 6, at=(r, "StereoGain:1", "Gain"), conv="lin2db",
          short="Level", sketch="kick.rumbleLevel"))

    # ---- MIX (step V): groups and buses, levels and sends, colour and space ---------------------------------
    add(P("mix.kick", "mix", "Levels", "Kick group", "dB", "lin", -36, 6, at=(kg, "Mixer", "Volume"), conv="lin2db",
          short="Kick", sketch="ch.kick.gain"))
    add(P("mix.perc", "mix", "Levels", "Perc group", "dB", "lin", -36, 6, at=("perc group", "Mixer", "Volume"), conv="lin2db",
          short="Perc", sketch="ch.perc.gain"))
    add(P("mix.sfx", "mix", "Levels", "SFX group", "dB", "lin", -36, 6, at=("SFX group", "Mixer", "Volume"), conv="lin2db",
          short="SFX", sketch="ch.sfx.gain"))
    add(P("mix.layerB", "mix", "Levels", "Hat layer B (perc 1 CH)", "dB", "lin", -36, 6,
          live="perc 1|Drum Rack > CH|Simpler|Volume", at=("perc 1", "branch:CH", "Volume"), conv="raw", nested=True,
          short="Layer B", sketch="mix.layerB",
          note="Too quiet to read as a new layer: +0.9-1.6 dB of highs alone. Drop it, raise it, or pair it with a loud layer."))
    add(P("mix.bassMono", "mix", "Mono low end", "Main bass mono", scale="toggle", at=("Main", "StereoGain:0", "BassMono"),
          conv="bool", short="Bass mono", sketch="mix.bassMono",
          note="Every reference keeps its low end mono; HW002 does not (correlation 0.88 under 120 Hz)."))
    add(P("mix.monoFreq", "mix", "Mono low end", "Bass mono below", "Hz", "log", 50, 500, at=("Main", "StereoGain:0", "BassMonoFrequency"),
          tried=[120, 169.3], short="Mono Hz", sketch="mix.monoFreq", note="Mono-low climb: on, below 169 Hz."))
    add(P("mix.spaceMix", "mix", "Space", "Supermassive mix (perc 2)", "%", "lin", 0, 100,
          at=("perc 2", "plugin:ValhallaSupermassive", "Mix"), conv="pct", tried=[28.3, 42.7], short="Mix",
          sketch="ch.perc.sendA@norm", note="Space climb: 28% to 43%. Batch 6: space is the aspect Anthony preferred."))
    add(P("mix.spaceFeedback", "mix", "Space", "Supermassive feedback", "%", "lin", 0, 100,
          at=("perc 2", "plugin:ValhallaSupermassive", "Feedback"), conv="pct", tried=[0, 83.5], short="Feedback",
          sketch="master.delayFeedback@norm"))
    add(P("mix.spaceDelay", "mix", "Space", "Supermassive delay", "%", "lin", 0, 100,
          at=("perc 2", "plugin:ValhallaSupermassive", "Delay_Ms"), conv="pct", tried=[6.7, 36.5], short="Delay",
          sketch="mix.spaceDelay@norm"))
    add(P("mix.spaceDensity", "mix", "Space", "Supermassive density", "%", "lin", 0, 100,
          at=("perc 2", "plugin:ValhallaSupermassive", "Density"), conv="pct", tried=[90.5, 98.4], short="Density",
          sketch="mix.spaceDensity@norm"))
    add(P("mix.spaceHighCut", "mix", "Space", "Supermassive high cut", "%", "lin", 0, 100,
          at=("perc 2", "plugin:ValhallaSupermassive", "HighCut"), conv="pct", tried=[42.8, 64.9], short="High cut",
          sketch="mix.spaceHighCut@norm"))
    add(P("mix.hatsBell", "mix", "Colour", "perc 2 bell (1 kHz)", "dB", "lin", -15, 15, at=("perc 2", "Eq8:0", "Bands.2/ParameterA/Gain"),
          tried=[0, 4.01], short="1 kHz", sketch="ch.perc.b2Gain", note="The mids are 6-8 dB under the references at 1-3.2 kHz."))
    add(P("mix.hatsAir", "mix", "Colour", "perc 2 high shelf (5 kHz)", "dB", "lin", -15, 15,
          at=("perc 2", "Eq8:0", "Bands.3/ParameterA/Gain"), tried=[-2.34, 0], short="5 kHz", sketch="ch.perc.highGain"))
    add(P("mix.hatsDrive", "mix", "Colour", "Decapitator drive (perc 2)", "%", "lin", 0, 100,
          at=("perc 2", "plugin:Decapitator", "Drive"), conv="pct", short="Hat drive", sketch="ch.perc.drive@norm"))
    add(P("mix.perc1Drive", "mix", "Colour", "COLDFIRE drive (perc 1)", "%", "lin", 0, 100,
          at=("perc 1", "plugin:Dist COLDFIRE", "Distortion A Drive"), conv="pct", short="Perc 1 drive", sketch="mix.perc1Drive@norm"))
    add(P("mix.mainRack", "mix", "Drop power", "Main glue rack", scale="toggle", at=("Main", "AudioEffectGroupDevice:0", "On"),
          conv="bool", short="Glue rack", sketch="mix.glueOn", note="Off in the set: EQ Eight, SPAN and Glue on the Main."))
    add(P("mix.glueThresh", "mix", "Drop power", "Glue threshold", "dB", "lin", -40, 0, at=("Main", "GlueCompressor", "Threshold"),
          short="Glue", sketch="master.glueThreshold",
          note="The references' peaks are denser (block crest 4.4-6.6 dB against 8.7). Density comes from clipping, "
               "saturation and a fuller drum bus."))
    add(P("mix.glueRatio", "mix", "Drop power", "Glue ratio", ":1", "enum", options=["2", "4", "10"],
          at=("Main", "GlueCompressor", "Ratio"), conv="raw", short="Glue ratio", sketch="mix.glueRatio"))
    add(P("mix.sfxVerb", "mix", "SFX bus", "SFX Hybrid wet", "%", "lin", 0, 100, at=("SFX group", "Hybrid:0", "DryWet"), conv="pct",
          short="SFX verb", sketch="ch.sfx.sendA@norm"))
    add(P("mix.sfxDecay", "mix", "SFX bus", "SFX Hybrid decay", "s", "log", 0.2, 20, at=("SFX group", "Hybrid:0", "Algorithm_Decay"),
          short="SFX decay", sketch="mix.sfxDecay"))
    add(P("mix.sfxThresh", "mix", "SFX bus", "SFX compressor threshold", "dB", "lin", -40, 0,
          at=("SFX group", "Compressor2:0", "Threshold"), conv="lin2db", short="SFX comp", sketch="ch.sfx.compThreshold"))
    add(P("mix.sfxLowCut", "mix", "SFX bus", "SFX EQ low band", "Hz", "log", 10, 2000,
          at=("SFX group", "Eq8:0", "Bands.0/ParameterA/Freq"), short="SFX low", sketch="ch.sfx.lowCut"))

    # ---- ARRANGE (step III): the Short's shape. Their "set" is the canonical Short, batch 4.3 track 1
    # (hands/archive/arrange_prototype/plan43.json b43-01): no gap before the kick, no SFX, no break.
    arr = "docs/hw002/batch-4.3-4.4-decisions.md"
    add(P("arr.length", "arrange", "Shape", "Length", "bars", "lin", 16, 40, set=20, step=4, tried=[22, 33], short="Bars",
          sketch="arr.length", note="Canonical shape: 20 bars, 30 s. The target is 33-50 s: 22-33 bars, on a 4/8-bar grid."))
    add(P("arr.intro", "arrange", "Shape", "Scooped-kick opening", "bars", "lin", 2, 8, set=4, step=2, short="Scoop bars",
          sketch="arr.intro", note="\"Final arrangement starts with the scooped kick.\" Never open on a single bar."))
    add(P("arr.kickIn", "arrange", "Shape", "Full kick enters", "bar", "lin", 3, 17, set=5, step=1, short="Kick in",
          sketch="arr.kickIn", note=f"With a long splash on the same bar ({arr})."))
    add(P("arr.preKick", "arrange", "Shape", "Before the kick", scale="enum", options=["wuh", "silence", "straight in"], set=2,
          short="Pre-kick", sketch="arr.preKick", note="Batch 4.2 tried the beatbox \"wuh\", a silence and the drop grid. "
          "The pre-kick sound felt cut short."))
    add(P("arr.preKickBeats", "arrange", "Shape", "Pre-kick length", "beats", "lin", 1, 8, set=4, step=1, short="Pre beats",
          sketch="arr.preKickBeats"))
    add(P("arr.hatA", "arrange", "Hats", "Layer A enters (open offbeats)", "bar", "lin", 1, 17, set=1, step=1, short="A",
          sketch="arr.hats", note="Hats A/AB/ABC/ABCD in 4/4/4/8 bars."))
    add(P("arr.hatB", "arrange", "Hats", "Layer B enters (16th closed)", "bar", "lin", 1, 25, set=5, step=1, short="B", sketch="arr.hats"))
    add(P("arr.hatC", "arrange", "Hats", "Layer C enters (8th rides)", "bar", "lin", 1, 25, set=9, step=1, short="C", sketch="arr.hats"))
    add(P("arr.hatD", "arrange", "Hats", "Layer D enters (bright 16ths)", "bar", "lin", 1, 33, set=13, step=1, short="D", sketch="arr.hats",
          note="\"A new layer has to add energy on its own.\""))
    add(P("arr.splashEvery", "arrange", "Splash", "Splash every", scale="enum", options=["4 bars", "8 bars", "16 bars", "once"], set=1,
          short="Every", sketch="arr.splash", note="\"Too many splashes. Spread them out by a factor of 2 or 4.\""))
    add(P("arr.splashLong", "arrange", "Splash", "Long splash", "beats", "lin", 1, 16, set=8, step=1, short="Long", sketch="arr.splash"))
    add(P("arr.splashShort", "arrange", "Splash", "Short splash", "beats", "lin", 1, 8, set=3, step=1, short="Short", sketch="arr.splash"))
    add(P("arr.splashLevel", "arrange", "Splash", "Splash level", "dB", "lin", -36, 6, at=(SPLASH, "Mixer", "Volume"), conv="lin2db",
          short="Splash dB", sketch="arr.splashLevel", note="The noise splash (6-2022-05-30-005) on the perc group."))
    add(P("arr.breakBars", "arrange", "Break", "Break length", "bars", "lin", 0, 16, set=8, step=4, short="Break",
          sketch="arr.break", note="The full song breaks at bars 81-96. Every reference has two breaks of 8+ bars; HW002 has one."))
    add(P("arr.breakAt", "arrange", "Break", "Break starts", "bar", "lin", 5, 33, set=17, step=1, short="Break at", sketch="arr.break"))
    add(P("arr.breakLevel", "arrange", "Break", "Break level", "dB", "lin", -12, 0, at=("Break group", "Mixer", "Volume"), conv="lin2db",
          tried=[-6, -4], short="Break dB", sketch="arr.breakLevel",
          note="At -4 dB the drop is only 0.4-0.9 LU over the loudest break bar; at -6 dB it is 2.4 LU over."))
    add(P("arr.secondBreak", "arrange", "Break", "A second break", scale="toggle", set=0, short="2nd break", sketch="arr.break"))
    add(P("arr.chord", "arrange", "Chord loop", "Chord loop in the Short", scale="toggle", set=0, short="Chord", sketch="arr.chord",
          note="The processed synth chord loop. Muted in the Short from 4.3 until 9 Oct."))
    add(P("arr.chordLevel", "arrange", "Chord loop", "Chord level", "dB", "lin", -24, 6, at=(CHORD, "StereoGain:0", "Gain"),
          conv="lin2db", tried=[-4.33, 3.67], short="Chord dB", sketch="arr.chordLevel",
          note="Sits about 21 LU under the mix. Batch 8.2 tried +4, +8 and +12 dB."))
    add(P("arr.chordWidth", "arrange", "Chord loop", "Chord width", "%", "lin", 0, 200, at=(CHORD, "StereoGain:0", "StereoWidth"),
          conv="pct", tried=[50, 150], short="Width", sketch="arr.chordWidth@norm", note="Batch 8.4: 50/100/150% adds 0.9/2.7/4.6 LU."))
    add(P("arr.sfxBuild", "arrange", "Arc", "SFX enters", scale="enum", options=["from the start", "with the kick", "at the drop", "withheld"],
          set=3, short="SFX in", sketch="arr.sfx", note="Rubric: the references withhold their SFX early, then build."))
    add(P("arr.dropBars", "arrange", "Arc", "Drop (ABCD) length", "bars", "lin", 4, 16, set=8, step=4, short="Drop", sketch="arr.hats"))

    # ---- COLLAGE (step I): the bed of found and library sounds ---------------------------------------------
    add(P("col.arcLevel", "collage", "Game audio", "ARC Raiders: Bastion level", "dB", "lin", -36, 6, at=(ARC, "StereoGain:0", "Gain"),
          conv="lin2db", short="Bastion", sketch="col.src-3.gain"))
    add(P("col.arcDelay", "collage", "Game audio", "Bastion Supermassive delay", "%", "lin", 0, 100,
          at=(ARC, "plugin:ValhallaSupermassive", "Delay_Ms"), conv="pct", short="Delay", sketch="col.src-3.delay@norm"))
    add(P("col.arcMassive", "collage", "Game audio", "Bastion Supermassive mix", "%", "lin", 0, 100,
          at=(ARC, "plugin:ValhallaSupermassive", "Mix"), conv="pct", short="Massive", sketch="col.src-3.space@norm"))
    add(P("col.arcVerb", "collage", "Game audio", "Bastion FlexVerb wet", "%", "lin", 0, 100,
          at=(ARC, "plugin:SSL Native FlexVerb", "Dry:Wet"), conv="pct", short="FlexVerb", sketch="col.src-3.verb@norm"))
    add(P("col.arcPitch", "collage", "Game audio", "Bastion clip pitch", "st", "lin", -24, 24, at=(ARC, "clip", "PitchCoarse"), step=1,
          live=f"{ARC}|clip|Transpose", nested=True, short="Pitch", sketch="col.src-3.pitch"))
    add(P("col.audioMassive", "collage", "Game audio", "11-Audio Supermassive mix", "%", "lin", 0, 100,
          at=("11-Audio", "plugin:ValhallaSupermassive", "Mix"), conv="pct", short="11 wash", sketch="col.wash@norm"))
    add(P("col.chordShine", "collage", "Chord loop", "Chord shine (1.2 kHz shelf)", "dB", "lin", -15, 15,
          at=(CHORD, "Eq8:0", "Bands.1/ParameterA/Gain"), tried=[6, 12], short="Shine", sketch="col.src-4.tone",
          note="A +12 dB shelf moves the mix's highs by 0.2 dB."))
    add(P("col.chordColour", "collage", "Chord loop", "Chord COLDFIRE colour", "%", "lin", 0, 100,
          at=(CHORD, "plugin:Dist COLDFIRE", "Color"), conv="pct", tried=[50, 100], short="Colour", sketch="col.src-4.drive@norm",
          src="HW002_121_pp_kit_c8x16.als",
          note="Batch 8.3. Costs 5.4 LU at any drive; a tilt that lifts the top octaves 4-9 dB."))
    add(P("col.chordTexture", "collage", "Chord loop", "Chord Supermassive mix", "%", "lin", 0, 100,
          at=(CHORD, "plugin:ValhallaSupermassive", "Mix"), conv="pct", tried=[30, 80], short="Texture", sketch="col.src-4.space@norm",
          note="\"Short and tight, more to change the texture and frequency.\" (batch 8.5)"))
    add(P("col.synthFreq", "collage", "Break synths", "Synth filter", "Hz", "log", 30, 18000,
          at=(SYNTH, "AutoFilter2:0", "Filter_Frequency"), short="Filter", sketch="col.src-5.filter"))
    add(P("col.synthRes", "collage", "Break synths", "Synth resonance", "%", "lin", 0, 125, at=(SYNTH, "AutoFilter2:0", "Filter_Resonance"),
          conv="pct", short="Res", sketch="col.src-5.res@norm"))
    add(P("col.synthLfo", "collage", "Break synths", "Synth filter LFO", "%", "lin", 0, 100, at=(SYNTH, "AutoFilter2:0", "Lfo_Amount"),
          conv="pct", short="LFO", sketch="col.src-5.lfo@norm"))
    add(P("col.synthDrive", "collage", "Break synths", "Synth Overdrive", "%", "lin", 0, 100, at=(SYNTH, "Overdrive:0", "Drive"),
          short="Overdrive", sketch="col.src-5.drive@norm"))
    add(P("col.synthMassive", "collage", "Break synths", "Synth Supermassive mix", "%", "lin", 0, 100,
          at=(SYNTH, "plugin:ValhallaSupermassive", "Mix"), conv="pct", short="Massive", sketch="col.src-5.space@norm"))
    add(P("col.recMassive", "collage", "Recordings", "2023-10-07 wash", "%", "lin", 0, 100,
          at=(REC, "plugin:ValhallaSupermassive:1", "Mix"), conv="pct", short="Wash", sketch="col.src-7.space@norm"))
    add(P("col.recPitch", "collage", "Recordings", "2023-10-07 clip pitch", "st", "lin", -24, 24, at=(REC, "clip", "PitchCoarse"),
          step=1, live=f"{REC}|clip|Transpose", nested=True, short="Pitch", sketch="col.src-7.pitch"))
    add(P("col.beatboxLevel", "collage", "Recordings", "Beatbox level", "dB", "lin", -36, 6, at=(BEATBOX, "StereoGain:0", "Gain"),
          conv="lin2db", short="Beatbox", sketch="col.src-8.gain", note="The \"wuh\" before the kick."))
    add(P("col.beatboxMassive", "collage", "Recordings", "Beatbox Supermassive mix", "%", "lin", 0, 100,
          at=(BEATBOX, "plugin:ValhallaSupermassive", "Mix"), conv="pct", short="Massive", sketch="col.src-8.space@norm"))
    add(P("col.breakSpace", "collage", "Break bus", "Break Hybrid wet", "%", "lin", 0, 100, at=("Break group", "Hybrid:0", "DryWet"),
          conv="pct", tried=[70, 90], short="Space", sketch="col.breakSpace@norm",
          note="Batch 8.6. Wetter takes 3-5 dB off the lows and the top."))
    add(P("col.breakDecay", "collage", "Break bus", "Break Hybrid decay", "s", "log", 0.2, 20, at=("Break group", "Hybrid:0", "Algorithm_Decay"),
          tried=[1.5, 8], short="Decay", sketch="col.breakDecay"))
    add(P("col.breakColour", "collage", "Break bus", "Break COLDFIRE colour", "%", "lin", 0, 100,
          at=("Break group", "plugin:Dist COLDFIRE", "Color"), conv="pct", tried=[30, 100], short="Colour", sketch="col.breakColour@norm",
          src="HW002_121_pp_kit_k8x16.als",
          note="Batch 8.7: 30% and 50% put the top 4 and 2 dB down; 100% puts it 3 dB up."))
    add(P("col.breakFold", "collage", "Break bus", "Break COLDFIRE drive (fold)", "%", "lin", 0, 100,
          at=("Break group", "plugin:Dist COLDFIRE", "Distortion A Drive"), conv="pct", tried=[40, 100], short="Fold",
          src="HW002_121_pp_kit_k8x16.als",
          sketch="col.breakFold@norm"))
    return L


# --- reading the set ---------------------------------------------------------------------------------------------
def tracks(als: Path) -> dict[str, ET.Element]:
    live = ET.fromstring(gzip.open(als).read()).find("LiveSet")
    out = {}
    main = live.find("MainTrack")
    for t in list(live.find("Tracks")) + [main if main is not None else live.find("MasterTrack")]:
        name = "Main" if t.tag in ("MainTrack", "MasterTrack") else t.find("Name/EffectiveName").get("Value")
        out[name] = t
    return out


def _plugin_name(d: ET.Element) -> str | None:
    for path in ("PluginDesc/VstPluginInfo/PlugName", "PluginDesc/Vst3PluginInfo/Name", "PluginDesc/AuPluginInfo/Name"):
        x = d.find(path)
        if x is not None:
            return x.get("Value")
    return None


def _device(chain: ET.Element, spec: str) -> ET.Element | None:
    """'Eq8:1' (the second EQ Eight), 'plugin:Decapitator', 'plugin:ValhallaSupermassive:1', 'GlueCompressor'."""
    devices = list(chain.find("Devices")) if chain.find("Devices") is not None else []
    if spec.startswith("plugin:"):
        name, _, idx = spec[7:].partition(":")
        hits = [d for d in devices if d.tag == "PluginDevice" and _plugin_name(d) == name]
    else:
        tag, _, idx = spec.partition(":")
        hits = [d for d in devices if d.tag == tag]
        if not hits:                                     # a nested device (e.g. Glue inside the Main's rack)
            hits = [d for d in chain.iter(tag)]
    i = int(idx or 0)
    return hits[i] if len(hits) > i else None


def _manual(dev: ET.Element, path: str) -> str | None:
    if dev.tag == "PluginDevice":
        for fp in dev.findall("ParameterList/PluginFloatParameter"):
            if fp.find("ParameterName").get("Value") == path:
                return fp.find("ParameterValue/Manual").get("Value")
        if path == "On":
            return dev.find("On/Manual").get("Value")
        return None
    el = dev.find(path)
    if el is None:                                       # search below for the last part (Simpler's Volume ...)
        last = path.split("/")[-1]
        el = next((x for x in dev.iter(last) if x.find("Manual") is not None), None)
    if el is None:
        return None
    m = el.find("Manual")
    return m.get("Value") if m is not None else None


def _branch(track: ET.Element, name: str) -> ET.Element | None:
    for br in track.iter():
        if br.tag.endswith("Branch") and br.find("Name") is not None:
            n = br.find("Name").get("Value") or (br.find("Name/EffectiveName").get("Value") if br.find("Name/EffectiveName") is not None else None)
            if n == name:
                return br
    return None


def read(tr: dict[str, ET.Element], at: tuple) -> str | None:
    track, device, path = at
    t = tr.get(track)
    if t is None:
        return None
    if device == "Mixer":
        return t.find(f"DeviceChain/Mixer/{path}/Manual").get("Value")
    if device == "clip":
        c = next(t.iter("AudioClip"), None)
        return c.find(path).get("Value") if c is not None and c.find(path) is not None else None
    if device.startswith("branch:"):
        br = _branch(t, device[7:])
        if br is None:
            return None
        if path == "Volume":                              # the pad's Simpler volume (dB); the chain mixers are all at 0 dB
            v = next((x.find("Manual") for x in br.iter("Volume") if x.find("Manual") is not None), None)
            return v.get("Value") if v is not None else None
        dev_spec, _, param = path.partition("/")
        for chain in br.iter():
            if chain.tag in ("AudioToAudioDeviceChain", "MidiToAudioDeviceChain") and chain.find("Devices") is not None:
                d = _device(chain, dev_spec)
                if d is not None:
                    return _manual(d, param)
        return None
    chain = t.find("DeviceChain/DeviceChain")
    d = _device(chain, device)
    if d is None:
        return None
    return d.find("On/Manual").get("Value") if path == "On" and d.tag != "PluginDevice" else _manual(d, path)


def convert(raw: str, conv: str) -> float:
    if raw in ("true", "false"):
        return 1.0 if raw == "true" else 0.0
    x = float(raw)
    return {
        "raw": x, "pct": x * 100, "bipct": x * 100, "bool": 1.0 if x else 0.0,
        "lin2db": 20 * math.log10(max(x, 1e-6)),
        "enum5": round(x * 4) if x <= 1 else x,
    }[conv]


def hands_id(p: P) -> str | None:
    if p.live is not None or p.at is None:
        return p.live
    track, device, path = p.at
    if device == "Mixer":
        return f"{track}|Mixer|{path}"
    if device.startswith("plugin:"):
        return f"{track}|{device.split(':')[0]}:{device.split(':')[1]}|{path}"
    tag, _, idx = device.partition(":")
    return f"{track}|{tag}:{idx or 0}|{path}"


def build(als: Path = SET, out: Path = OUT) -> list[dict[str, Any]]:
    tr = tracks(als)
    others: dict[str, dict] = {}
    rows, missing = [], []
    for p in plan():
        if p.at is not None:
            if p.src:
                others.setdefault(p.src, tracks(als.parent / p.src))
                p.note = ((p.note + " ") if p.note else "") + f"Value from {p.src}, where COLDFIRE was opened."
            raw = read(others[p.src] if p.src else tr, p.at)
            if raw is None:
                missing.append(p.id)
            else:
                v = convert(raw, p.conv)
                p.set = round(v, 4)
        if p.set is None:
            p.set = p.min
        row = {k: v for k, v in asdict(p).items() if v not in (None, [], {}) and k not in ("at", "conv", "extra", "src")}
        if p.stage in ("kick", "mix"):           # the stems' channels: one sketch per param (static/lab/js/audio/sketches.js)
            row["sketch"] = p.id
        row["live"] = hands_id(p)
        row["origin"] = "arrangement" if p.at is None else "set"
        if p.nested:
            row["nested"] = True
        rows.append(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"set": als.name, "count": len(rows), "params": rows}, indent=1) + "\n")
    if missing:
        print("not found in the set (their value is the range's start):", ", ".join(missing))
    return rows
