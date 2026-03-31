"""Schranz / SNTS percussion study config (160 BPM, OH/CH/RD groups).

Migrated from:
  ableton-live-vm/recipe-experiment_2026-03-26/configs/schranz_snts.py

NOTE: Some fields used in the original config reference models not yet
migrated to hands.models (DeviceSource, ParallelRack, RackChain,
ArrangementConfig, SongStructure, Section, SectionTrack, sidechain on
RumbleConfig/PercConfig). Those sections are stubbed with TODO comments.
Run `uv run python examples/build_schranz.py` for a dry-run step listing.
"""
from __future__ import annotations

import os

from hands.models import (
    DeviceSpec,
    EQ8Band,
    EQ8Spec,
    KickConfig,
    MidiNote,
    MidiPattern,
    PercConfig,
    PercGroup,
    ProjectConfig,
    RumbleConfig,
    SamplePad,
)

_DEFAULT_SAMPLE_BASE = (
    "/Users/anthonybecker/Desktop/tmsmsm/current projects/"
    "Schranz, SNTS percussion/anthony_2026-03-15/"
    "1_anthony_2026-03-15 Project/Samples/Imported"
)
SAMPLE_BASE = os.getenv("SCHRANZ_SAMPLE_BASE", _DEFAULT_SAMPLE_BASE)


# ---------------------------------------------------------------------------
# Percussion groups
# ---------------------------------------------------------------------------

def _rides() -> PercGroup:
    pads = tuple(
        SamplePad(note=n, name=name)
        for n, name in [
            (56, "VEC1 Cymbals RD 23"), (55, "VEC1 Cymbals RD 22"),
            (54, "VEC1 Cymbals RD 21"), (53, "VEC1 Cymbals RD 20"),
            (52, "VEC1 Cymbals RD 19"), (51, "VEC1 Cymbals RD 18"),
            (50, "VEC1 Cymbals RD 17"), (49, "VEC1 Cymbals RD 16"),
            (48, "VEC1 Cymbals RD 15"), (47, "VEC1 Cymbals RD 14"),
            (46, "VEC1 Cymbals RD 13"), (44, "VEC1 Cymbals RD 11"),
        ]
    )
    return PercGroup(
        label="rides",
        samples=pads,
        main=SamplePad(note=45, name="VEC1 Cymbals RD 12"),
        main_devices=(
            # TODO: DeviceSource.PLUGINS not yet in hands.models
            DeviceSpec(name="GClip", params={"Gain": 0, "Clip": 1, "Softness": 0}),
        ),
    )


def _closed_hh() -> PercGroup:
    pads = tuple(
        SamplePad(note=n, name=name)
        for n, name in [
            (40, "VEC1 Cymbals  CH 32"), (39, "VEC1 Cymbals  CH 31"),
            (38, "VEC1 Cymbals  CH 30"), (37, "VEC1 Cymbals  CH 29"),
            (36, "VEC1 Cymbals  CH 28"), (35, "VEC1 Cymbals  CH 27"),
            (34, "VEC1 Cymbals  CH 26"), (32, "VEC1 Cymbals  CH 24"),
            (31, "VEC1 Cymbals  CH 23"), (30, "VEC1 Cymbals  CH 22"),
            (29, "VEC1 Cymbals  CH 21"), (28, "VEC1 Cymbals  CH 20"),
            (27, "VEC1 Cymbals  CH 19"), (26, "VEC1 Cymbals  CH 18"),
            (25, "VEC1 Cymbals  CH 17"), (24, "VEC1 Cymbals  CH 16"),
        ]
    )
    return PercGroup(
        label="closed_hh",
        samples=pads,
        main=SamplePad(note=33, name="VEC1 Cymbals  CH 25"),
    )


def _open_hh() -> PercGroup:
    pads = tuple(
        SamplePad(note=n, name=name)
        for n, name in [
            (20, "VEC1 Cymbals  OH 071"), (19, "VEC1 Cymbals  OH 070"),
            (18, "VEC1 Cymbals  OH 069"), (17, "VEC1 Cymbals  OH 068"),
            (16, "VEC1 Cymbals  OH 067"), (15, "VEC1 Cymbals  OH 066"),
            (14, "VEC1 Cymbals  OH 065"), (13, "VEC1 Cymbals  OH 064"),
            (12, "VEC1 Cymbals  OH 063"), (10, "VEC1 Cymbals  OH 061"),
            (9,  "VEC1 Cymbals  OH 060"), (8,  "VEC1 Cymbals  OH 059"),
            (7,  "VEC1 Cymbals  OH 058"), (6,  "VEC1 Cymbals  OH 057"),
            (5,  "VEC1 Cymbals  OH 056"), (4,  "VEC1 Cymbals  OH 055"),
        ]
    )
    return PercGroup(
        label="open_hh",
        samples=pads,
        main=SamplePad(note=11, name="VEC1 Cymbals  OH 062"),
    )


def _perc_midi() -> MidiPattern:
    oh, ch, rd = 11, 33, 45
    notes: list[MidiNote] = []
    for t, v in [(0, 100), (.5, 78), (1, 100), (1.5, 100),
                 (2, 100), (2.5, 82), (3, 100), (3.5, 100)]:
        notes.append(MidiNote(pitch=oh, time=t, duration=0.25, velocity=v))
    for t, v in [(0, 77), (.25, 66), (.5, 100), (.75, 89),
                 (1, 100), (1.25, 66), (1.5, 100), (1.75, 93),
                 (2, 100), (2.25, 66), (2.5, 100), (2.75, 91),
                 (3, 100), (3.25, 66), (3.5, 100), (3.75, 85)]:
        notes.append(MidiNote(pitch=ch, time=t, duration=0.25, velocity=v))
    for t in [0.5, 1.5, 2.5, 3.5]:
        notes.append(MidiNote(pitch=rd, time=t, duration=0.25, velocity=100))
    return MidiPattern(name="perc_pattern", length_beats=4.0, notes=tuple(notes))


# ---------------------------------------------------------------------------
# Kick
# ---------------------------------------------------------------------------

def _kick_samples() -> tuple[SamplePad, ...]:
    return tuple(
        SamplePad(note=n, name=name)
        for n, name in [
            (84, "VEC2 Bassdrums Clubby 059"),
            (83, "VEC2 Bassdrums Clubby 060"),
            (82, "VEC2 Bassdrums Clubby 061"),
            (81, "VEC2 Bassdrums Clubby 062"),
            (80, "VEC2 Bassdrums Clubby 063"),
            (79, "VEC2 Bassdrums Clubby 064"),
            (78, "VEC2 Bassdrums Clubby 065"),
            (77, "VEC2 Bassdrums Clubby 111"),
            (76, "VEC2 Bassdrums Clubby 112"),
            (75, "VEC2 Bassdrums Clubby 113"),
            (74, "VEC2 Bassdrums Clubby 114"),
            (73, "VEC2 Bassdrums Clubby 115"),
            (72, "VEC2 Bassdrums Clubby 116"),
            (71, "VEC2 Bassdrums Clubby 117"),
            (70, "VEC2 Bassdrums Clubby 118"),
            (69, "VEC2 Bassdrums Clubby 119"),
            (68, "VEC2 Bassdrums Clubby 120"),
            (67, "VEC2 Bassdrums Clubby 121"),
        ]
    )


def _kick_midi() -> MidiPattern:
    notes = tuple(
        MidiNote(pitch=84, time=t, duration=0.25, velocity=100)
        for t in [0, 1, 2, 3]
    )
    return MidiPattern(name="kick_pattern", length_beats=4.0, notes=notes)


# ---------------------------------------------------------------------------
# Rumble device chain
# ---------------------------------------------------------------------------

_DECAP_RUMBLE = DeviceSpec(
    name="Decapitator",
    params={"Style": 0.0, "Drive": 0.27, "LowCut": 0.1903,
            "Tone": 0.2375, "HighCut": 0.41,
            "Mix": 1.0, "OutputTrim": 0.8583},
)

_UTILITY_RUMBLE = DeviceSpec(
    name="Utility", params={"Gain": 0.4084, "Width": 0.877},
)

_SHIFTER_RUMBLE = DeviceSpec(
    name="Shifter", params={"Fine": 0.3175, "Dry/Wet": 1.0},
)

_EQ8_RUMBLE = EQ8Spec(bands=(
    EQ8Band(band=1, mode=2, freq_hz=30.95, gain=-14.26, q_norm=0.6),
    EQ8Band(band=2, mode=3, freq_hz=59.94, gain=6.57),
    EQ8Band(band=3, mode=3, freq_hz=272.34, gain=-9.05),
    EQ8Band(band=4, mode=5, freq_hz=5000.0, gain=0.0),
))


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------

def schranz_config() -> ProjectConfig:
    return ProjectConfig(
        name="Schranz/SNTS Percussion Study",
        tempo=160.0,
        # TODO: sample_base not yet in ProjectConfig — add when migrating models
        percussion=PercConfig(
            groups=(_rides(), _closed_hh(), _open_hh()),
            # TODO: bus_rack (ParallelRack) not yet in hands.models
            bus_distortion=DeviceSpec(
                name="Decapitator",
                params={"Style": 0.0, "Drive": 0.74, "LowCut": 0.0,
                        "Tone": 0.7292, "HighCut": 0.83,
                        "Mix": 0.68, "OutputTrim": 0.5667},
            ),
            bus_eq=EQ8Spec(bands=(
                EQ8Band(band=1, mode=2, freq_hz=86.13, gain=-15.0, q_norm=0.55),
                EQ8Band(band=3, mode=3, freq_hz=550.37, gain=-12.77),
            )),
            # TODO: bus_sidechain not yet in PercConfig
            midi=_perc_midi(),
        ),
        kick=KickConfig(
            samples=_kick_samples(),
            main=SamplePad(note=84, name="VEC2 Bassdrums Clubby 059"),
            main_distortion=DeviceSpec(
                name="Dist COLDFIRE",
                # TODO: DeviceSource.PLUGINS not yet in hands.models
                params={"Distortion B Drive": 0.408},
            ),
            track_eq=EQ8Spec(bands=(
                EQ8Band(band=1, mode=1, freq_hz=30.03, gain=-15.0, q_norm=0.42),
                EQ8Band(band=2, mode=3, freq_hz=53.88, gain=3.1),
                EQ8Band(band=3, mode=3, freq_hz=1000.0, gain=0.0),
            )),
            midi=_kick_midi(),
        ),
        rumble=RumbleConfig(
            source_description="Bounced from kick drum rack",
            devices=(_UTILITY_RUMBLE, _SHIFTER_RUMBLE, _DECAP_RUMBLE, _EQ8_RUMBLE),
            # TODO: sidechain (LFOTool) not yet in RumbleConfig
            fundamental_target_hz=50.0,
            width=0.877,
        ),
        # TODO: arrangement (ArrangementConfig) not yet in ProjectConfig
    )


if __name__ == "__main__":
    from hands.builder import ProjectBuilder
    from hands.transport import DryRunTransport
    from hands.runner import StepRunner, ManualPolicy

    config = schranz_config()
    builder = ProjectBuilder(config)
    steps = builder.build_steps()
    print(f"Generated {len(steps)} steps for '{config.name}':")
    for i, step in enumerate(steps):
        print(f"  [{i:2d}] {step.label}")

    print("\n--- Dry run ---")
    transport = DryRunTransport()
    runner = StepRunner(transport)
    runner.execute(steps, on_manual=ManualPolicy.SKIP)
