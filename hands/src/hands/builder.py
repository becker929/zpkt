"""ProjectBuilder: turns a ProjectConfig into ordered MCP execute() steps."""
from __future__ import annotations

from hands.codegen import (
    Step, gen_configure_eq8, gen_configure_rack_chain, gen_create_tracks,
    gen_load_device, gen_load_device_to_pad, gen_load_sample_to_pad,
    gen_manual_rack_setup, gen_midi_clip, gen_rename_tracks,
    gen_set_arrangement_loop, gen_set_pad_chain_device_params, gen_set_params,
    gen_set_simpler_params, gen_set_tempo, gen_tile_session_to_arrangement,
)
from hands.models import (
    DeviceSource, DeviceSpec, EQ8Spec, MidiPattern, PercConfig, ProjectConfig,
    SamplePad, SongStructure,
)

_EQ8 = DeviceSpec(name="EQ Eight")
_RACK = DeviceSpec(name="Audio Effect Rack")
_DRUM_RACK = DeviceSpec(name="Drum Rack", source=DeviceSource.DRUMS)


class ProjectBuilder:
    """Generates an ordered list of MCP steps from a ProjectConfig."""

    def __init__(self, config: ProjectConfig) -> None:
        self._cfg = config

    def build_steps(self) -> list[Step]:
        steps: list[Step] = []
        steps.extend(self._session_steps())
        steps.extend(self._percussion_steps())
        steps.extend(self._kick_steps())
        steps.extend(self._rumble_steps())
        if self._cfg.mid_layer is not None:
            steps.extend(self._mid_layer_steps())
        if self._cfg.arrangement is not None:
            steps.extend(self._arrangement_steps())
        return steps

    def reference_json(self) -> str:
        return self._cfg.model_dump_json(indent=2)

    # ------------------------------------------------------------------
    # Track layout
    # ------------------------------------------------------------------

    def _track_layout(self) -> list[tuple[str, str]]:
        layout: list[tuple[str, str]] = [("1-ref_kick", "audio")]
        if self._cfg.percussion.groups:
            layout.append(("2-Perc", "midi"))
        if self._cfg.kick.samples:
            layout.append(("3-Kick", "midi"))
        if self._cfg.rumble.devices:
            layout.append(("4-Rumble", "audio"))
        if self._cfg.mid_layer is not None:
            layout.append(("5-MidLayer", "midi"))
        return layout

    def _track_index(self, prefix: str) -> int:
        for i, (name, _) in enumerate(self._track_layout()):
            if name.startswith(prefix):
                return i
        raise KeyError(f"No track with prefix {prefix!r}")

    @staticmethod
    def _load_and_configure(track_idx: int, devices: tuple, label: str) -> list[Step]:
        steps: list[Step] = []
        for device_idx, dev in enumerate(devices):
            if isinstance(dev, EQ8Spec):
                steps.append(gen_load_device(track_idx, _EQ8))
                steps.append(gen_configure_eq8(track_idx, device_idx, dev, label))
            elif isinstance(dev, DeviceSpec):
                steps.append(gen_load_device(track_idx, dev))
                if dev.params:
                    steps.append(gen_set_params(track_idx, device_idx, dev.params, dev.name))
        return steps

    # ------------------------------------------------------------------
    # Drum pad helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pad_setup_steps(
        track_idx: int, drum_rack_idx: int, pad: SamplePad, extra_devices: tuple,
    ) -> list[Step]:
        steps: list[Step] = [
            gen_load_sample_to_pad(track_idx, drum_rack_idx, pad.note, pad.name),
        ]
        if pad.transpose != 0 or pad.start != 0 or pad.end is not None or pad.volume != 1.0:
            steps.append(gen_set_simpler_params(track_idx, drum_rack_idx, pad.note, pad))
        for chain_device_idx, device in enumerate(extra_devices, start=1):
            steps.append(gen_load_device_to_pad(track_idx, drum_rack_idx, pad.note, device))
            if device.params:
                steps.append(gen_set_pad_chain_device_params(
                    track_idx, drum_rack_idx, pad.note,
                    chain_device_idx, device.params, device.name,
                ))
        return steps

    # ------------------------------------------------------------------
    # Session setup
    # ------------------------------------------------------------------

    def _session_steps(self) -> list[Step]:
        layout = self._track_layout()
        return [gen_set_tempo(self._cfg.tempo), gen_create_tracks(layout), gen_rename_tracks(layout)]

    # ------------------------------------------------------------------
    # Percussion + drum bus
    # ------------------------------------------------------------------

    def _percussion_steps(self) -> list[Step]:
        perc = self._cfg.percussion
        if not perc.groups:
            return []
        ti = self._track_index("2-")
        steps: list[Step] = [gen_load_device(ti, _DRUM_RACK)]
        for group in perc.groups:
            if group.main is not None:
                steps.extend(self._pad_setup_steps(
                    ti, 0, group.main, group.main.devices + group.main_devices,
                ))
        bus_devices = self._collect_bus_devices(perc)
        for dev in bus_devices:
            steps.append(gen_load_device(ti, dev))
        steps.extend(self._configure_bus(perc, ti, bus_devices))
        if perc.bus_rack is not None:
            steps.append(gen_manual_rack_setup(ti, perc.bus_rack))
            for ci, chain in enumerate(perc.bus_rack.chains):
                for di, dev in enumerate(chain.devices):
                    if dev.params:
                        steps.append(gen_configure_rack_chain(ti, 1, ci, di, dev.params, dev.name))
        if perc.midi is not None:
            steps.append(gen_midi_clip(ti, 0, perc.midi))
        return steps

    @staticmethod
    def _collect_bus_devices(perc: PercConfig) -> list[DeviceSpec]:
        devs: list[DeviceSpec] = []
        if perc.bus_rack is not None:
            devs.append(_RACK)
        if perc.bus_distortion is not None:
            devs.append(perc.bus_distortion)
        if perc.bus_eq is not None:
            devs.append(_EQ8)
        if perc.bus_sidechain is not None:
            devs.append(perc.bus_sidechain)
        return devs

    @staticmethod
    def _configure_bus(perc: PercConfig, ti: int, bus_devices: list[DeviceSpec]) -> list[Step]:
        steps: list[Step] = []
        for i, dev in enumerate(bus_devices):
            di = 1 + i
            if dev.name == "Audio Effect Rack":
                continue
            if dev.name == "EQ Eight" and perc.bus_eq is not None:
                steps.append(gen_configure_eq8(ti, di, perc.bus_eq, "perc bus"))
            elif dev.params:
                steps.append(gen_set_params(ti, di, dev.params, dev.name))
        return steps

    # ------------------------------------------------------------------
    # Kick
    # ------------------------------------------------------------------

    def _kick_steps(self) -> list[Step]:
        kick = self._cfg.kick
        if not kick.samples:
            return []
        ti = self._track_index("3-")
        steps: list[Step] = [gen_load_device(ti, _DRUM_RACK)]
        if kick.main is not None:
            steps.extend(self._pad_setup_steps(ti, 0, kick.main, kick.main.devices))
        track_dev_idx = 1
        if kick.main_distortion is not None:
            steps.append(gen_load_device(ti, kick.main_distortion))
            if kick.main_distortion.params:
                steps.append(gen_set_params(
                    ti, track_dev_idx, kick.main_distortion.params, kick.main_distortion.name,
                ))
            track_dev_idx += 1
        if kick.track_eq is not None:
            steps.append(gen_load_device(ti, _EQ8))
            steps.append(gen_configure_eq8(ti, track_dev_idx, kick.track_eq, "kick"))
        if kick.midi is not None:
            steps.append(gen_midi_clip(ti, 0, kick.midi))
        return steps

    # ------------------------------------------------------------------
    # Rumble
    # ------------------------------------------------------------------

    def _rumble_steps(self) -> list[Step]:
        rumble = self._cfg.rumble
        if not rumble.devices:
            return []
        ti = self._track_index("4-")
        steps = list(self._load_and_configure(ti, rumble.devices, "rumble"))
        if rumble.sidechain is not None:
            steps.append(gen_load_device(ti, rumble.sidechain))
        return steps

    # ------------------------------------------------------------------
    # Mid-layer
    # ------------------------------------------------------------------

    def _mid_layer_steps(self) -> list[Step]:
        ml = self._cfg.mid_layer
        if ml is None:
            return []
        ti = self._track_index("5-")
        steps = list(self._load_and_configure(ti, ml.devices, "mid-layer"))
        if ml.midi is not None:
            steps.append(gen_midi_clip(ti, 0, ml.midi))
        return steps

    # ------------------------------------------------------------------
    # Arrangement
    # ------------------------------------------------------------------

    def _clip_length(self, track_prefix: str) -> float:
        cfg = self._cfg
        midi_by_prefix: dict[str, MidiPattern | None] = {"2-": cfg.percussion.midi, "3-": cfg.kick.midi}
        if cfg.mid_layer is not None:
            midi_by_prefix["5-"] = cfg.mid_layer.midi
        pattern = midi_by_prefix.get(track_prefix)
        return pattern.length_beats if pattern is not None else 4.0

    def _flatten_structure(self, structure: SongStructure) -> list[Step]:
        steps: list[Step] = []
        beat_offset = 0.0
        for section in structure.sections:
            section_beats = section.length_bars * structure.beats_per_bar
            for st in section.tracks:
                if not st.enabled:
                    continue
                steps.append(gen_tile_session_to_arrangement(
                    track_idx=self._track_index(st.track_prefix),
                    session_slot=st.session_slot,
                    start_beat=beat_offset,
                    end_beat=beat_offset + section_beats,
                    clip_length=self._clip_length(st.track_prefix),
                ))
            beat_offset += section_beats
        return steps

    def _arrangement_steps(self) -> list[Step]:
        arr = self._cfg.arrangement
        if arr is None:
            return []
        steps: list[Step] = []
        if arr.structure is not None:
            steps.extend(self._flatten_structure(arr.structure))
        else:
            for clip_spec in arr.clips:
                steps.append(gen_tile_session_to_arrangement(
                    track_idx=self._track_index(clip_spec.track_prefix),
                    session_slot=clip_spec.source_session_slot,
                    start_beat=clip_spec.start_beat,
                    end_beat=clip_spec.start_beat + clip_spec.length_beats,
                    clip_length=self._clip_length(clip_spec.track_prefix),
                ))
        steps.append(gen_set_arrangement_loop(arr.loop, arr.loop_start, arr.loop_length))
        return steps
