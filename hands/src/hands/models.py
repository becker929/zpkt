"""Pydantic models for the hands layer.

All models are frozen (immutable) and serialise cleanly to JSON.
These are the source of truth for ProjectConfig and Feedback schemas.

No imports from ears or taste — JSON is the cross-repo interface.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

_FROZEN: dict[str, Any] = {"frozen": True}


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class DeviceSource(str, Enum):
    """Browser subtree where Live finds a device."""
    BUILTIN = "audio_effects"
    PLUGINS = "plugins"
    DRUMS = "drums"
    INSTRUMENTS = "instruments"
    MIDI_FX = "midi_effects"


class DeviceSpec(BaseModel):
    """A single audio device with optional parameter overrides."""

    model_config = _FROZEN  # type: ignore[assignment]

    kind: Literal["device"] = "device"
    name: str
    source: DeviceSource = DeviceSource.BUILTIN
    params: dict[str, float] = Field(default_factory=dict)


class EQ8Band(BaseModel):
    """One band of an Ableton EQ Eight device."""

    model_config = _FROZEN  # type: ignore[assignment]

    band: int = Field(ge=1, le=8)
    mode: int = Field(default=3, ge=0, le=7)
    freq_hz: float = Field(gt=0.0)
    gain: float = Field(default=0.0, ge=-15.0, le=15.0)
    q_norm: float = Field(default=0.7071, gt=0.0, le=1.0)


class EQ8Spec(BaseModel):
    """Full EQ Eight configuration."""

    model_config = _FROZEN  # type: ignore[assignment]

    kind: Literal["eq8"] = "eq8"
    bands: tuple[EQ8Band, ...] = ()


TrackDevice = Annotated[
    Union[DeviceSpec, EQ8Spec],
    Field(discriminator="kind"),
]


class RackChain(BaseModel):
    """One chain inside an Audio Effect Rack."""

    model_config = _FROZEN  # type: ignore[assignment]

    name: str
    devices: tuple[DeviceSpec, ...] = ()
    volume: float = 1.0


class ParallelRack(BaseModel):
    """Audio Effect Rack with named parallel chains."""

    model_config = _FROZEN  # type: ignore[assignment]

    chains: tuple[RackChain, ...] = ()


# ---------------------------------------------------------------------------
# Sample / pad layer
# ---------------------------------------------------------------------------

class SamplePad(BaseModel):
    """A single drum pad: MIDI note, sample name, optional Simpler trim.

    `devices` holds per-pad chain devices (loaded after the Simpler).
    `start`/`end` are percentages (0-100) mapped to Simpler S Start / S Length.
    """

    model_config = _FROZEN  # type: ignore[assignment]

    note: int = Field(ge=0, le=127)
    name: str
    transpose: int = Field(default=0, ge=-24, le=24)
    start: int = Field(default=0, ge=0, le=100)
    end: int | None = Field(default=None, ge=0, le=100)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    devices: tuple[DeviceSpec, ...] = ()

    @model_validator(mode="after")
    def _validate_start_end(self) -> "SamplePad":
        if self.end is not None and self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be greater than start ({self.start})")
        return self


class MidiNote(BaseModel):
    """A single MIDI note event."""

    model_config = _FROZEN  # type: ignore[assignment]

    pitch: int = Field(ge=0, le=127)
    time: float = Field(ge=0.0)
    duration: float = Field(gt=0.0)
    velocity: int = Field(default=100, ge=1, le=127)


class MidiPattern(BaseModel):
    """A loopable MIDI clip."""

    model_config = _FROZEN  # type: ignore[assignment]

    name: str
    length_beats: float = Field(default=4.0, gt=0.0)
    notes: tuple[MidiNote, ...] = ()
    loop: bool = True


class PercGroup(BaseModel):
    """A named group of percussion pads sharing a MIDI note bank."""

    model_config = _FROZEN  # type: ignore[assignment]

    label: str
    samples: tuple[SamplePad, ...] = ()
    main: SamplePad | None = None
    main_devices: tuple[DeviceSpec, ...] = ()


# ---------------------------------------------------------------------------
# Track-level configs
# ---------------------------------------------------------------------------

class PercConfig(BaseModel):
    """Full percussion section: groups, bus chain, MIDI pattern."""

    model_config = _FROZEN  # type: ignore[assignment]

    groups: tuple[PercGroup, ...] = ()
    bus_rack: ParallelRack | None = None
    bus_distortion: DeviceSpec | None = None
    bus_eq: EQ8Spec | None = None
    bus_sidechain: DeviceSpec | None = None
    midi: MidiPattern | None = None
    starting_pad_volume_db: float = -15.0


class KickConfig(BaseModel):
    """Kick drum section: samples, distortion, EQ, MIDI pattern."""

    model_config = _FROZEN  # type: ignore[assignment]

    samples: tuple[SamplePad, ...] = ()
    main: SamplePad | None = None
    main_distortion: DeviceSpec | None = None
    main_rack: ParallelRack | None = None
    group_devices: tuple[TrackDevice, ...] = ()
    track_eq: EQ8Spec | None = None
    transient_shaper: DeviceSpec | None = None
    midi: MidiPattern | None = None


class RumbleConfig(BaseModel):
    """Sub-bass rumble section: processing chain and metadata."""

    model_config = _FROZEN  # type: ignore[assignment]

    source_description: str = ""
    devices: tuple[TrackDevice, ...] = ()
    sidechain: DeviceSpec | None = None
    lowpass_hz: float | None = None
    fundamental_target_hz: float = 50.0
    width: float = Field(default=1.0, ge=0.0, le=1.0)


class MidLayerConfig(BaseModel):
    """Mid-layer section: devices and optional MIDI pattern."""

    model_config = _FROZEN  # type: ignore[assignment]

    devices: tuple[TrackDevice, ...] = ()
    midi: MidiPattern | None = None


# ---------------------------------------------------------------------------
# Arrangement
# ---------------------------------------------------------------------------

class ArrangementClip(BaseModel):
    """One clip placed in the arrangement view."""

    model_config = _FROZEN  # type: ignore[assignment]

    track_prefix: str
    start_beat: float = Field(ge=0.0)
    length_beats: float = Field(gt=0.0)
    source_session_slot: int = Field(default=0, ge=0)


class SectionTrack(BaseModel):
    """One track's behaviour within a song section."""

    model_config = _FROZEN  # type: ignore[assignment]

    track_prefix: str
    session_slot: int = Field(default=0, ge=0)
    enabled: bool = True


class Section(BaseModel):
    """A named time span in the arrangement (intro, drop, etc.)."""

    model_config = _FROZEN  # type: ignore[assignment]

    name: str
    length_bars: int = Field(gt=0)
    tracks: tuple[SectionTrack, ...] = ()


class SongStructure(BaseModel):
    """Section-based song structure flattened into tiled clips."""

    model_config = _FROZEN  # type: ignore[assignment]

    sections: tuple[Section, ...] = ()
    beats_per_bar: int = Field(default=4, gt=0)

    def total_beats(self) -> float:
        return sum(s.length_bars * self.beats_per_bar for s in self.sections)


class ArrangementConfig(BaseModel):
    """Arrangement view layout: which session clips go where."""

    model_config = _FROZEN  # type: ignore[assignment]

    clips: tuple[ArrangementClip, ...] = ()
    structure: SongStructure | None = None
    loop: bool = False
    loop_start: float = Field(default=0.0, ge=0.0)
    loop_length: float = Field(default=32.0, gt=0.0)
    total_bars: int = Field(default=32, gt=0)


# ---------------------------------------------------------------------------
# Top-level project
# ---------------------------------------------------------------------------

class ProjectConfig(BaseModel):
    """Top-level declarative project configuration.

    Produced by hands and consumed by the taste loop orchestrator.
    Serialises to JSON for cross-repo communication.
    """

    model_config = _FROZEN  # type: ignore[assignment]

    name: str
    tempo: float = Field(default=140.0, gt=0.0, lt=300.0)
    sample_base: str = ""
    percussion: PercConfig = Field(default_factory=PercConfig)
    kick: KickConfig = Field(default_factory=KickConfig)
    rumble: RumbleConfig = Field(default_factory=RumbleConfig)
    mid_layer: MidLayerConfig | None = None
    arrangement: ArrangementConfig | None = None


class Feedback(BaseModel):
    """Human feedback captured by the vibe tool.

    Produced by hands (vibe server) and consumed by the taste loop.
    """

    model_config = _FROZEN  # type: ignore[assignment]

    session_id: str
    render_path: str
    text: str
    timestamp_utc: str
    rating: int | None = Field(default=None, ge=1, le=5)
