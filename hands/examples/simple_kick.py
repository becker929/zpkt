"""Minimal single-kick example for the hands layer.

Demonstrates ProjectConfig → builder → dry-run output.
"""
from hands.models import KickConfig, MidiNote, MidiPattern, ProjectConfig, SamplePad
from hands.builder import ProjectBuilder
from hands.transport import DryRunTransport
from hands.runner import StepRunner, ManualPolicy

config = ProjectConfig(
    name="Simple Kick",
    tempo=130.0,
    kick=KickConfig(
        main=SamplePad(note=36, name="VEC2 Bassdrums Clubby 001"),
        midi=MidiPattern(
            name="kick_4on4",
            length_beats=4.0,
            notes=tuple(
                MidiNote(pitch=36, time=float(i), duration=0.25, velocity=100)
                for i in range(4)
            ),
        ),
    ),
)

if __name__ == "__main__":
    builder = ProjectBuilder(config)
    steps = builder.build_steps()
    print(f"Generated {len(steps)} steps:")
    for i, step in enumerate(steps):
        print(f"  [{i:2d}] {step.label}")

    print("\n--- Dry run ---")
    transport = DryRunTransport()
    runner = StepRunner(transport)
    runner.execute(steps, on_manual=ManualPolicy.SKIP)
