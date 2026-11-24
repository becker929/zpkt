"""Short, checked Live steps for scripts that build and render sets: parameters in the units Live shows, a track's
mixer, browser loads, and Save As and the export by the menu (hands.live.export).

    live = LiveOps(LiveClient(), staging=Path("~/renders/staging").expanduser())
    live.load_item("song.tracks[0]", "instruments", None, "Operator")
    live.setp("song.tracks[0].devices[0]", {"Filter Freq": "1.2 kHz", "Osc-A Wave": "Saw D"})
    live.export(Path("take.wav"), 0.0, 64.0)

Everything a step needs is on the object (the client, the folder exports are staged in, how the Save panel reaches
a folder), so two scripts in one process never change each other's settings. Each LOM call stays short (well under
the Remote Script's 12 s) and never reads back what it wrote in the same call, which crashes Live (ableton-guide
rule 1): the read-backs here are separate calls. A step that finds Live other than it expects raises
hands.live.session.Guard saying what it found.

These came from the SH001 recipe's liveops.py (Oct 2026), which the booth, the arranger and the mix desk loaded by
path; that script is archived with the other piece scripts (zpkt-archive).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hands.live import export as gui_export
from hands.live import session
from hands.live.inlive import with_source
from hands.live.session import stop
from hands.live.transport import McpTransport

PER_CALL = 16  # parameters set in one call (ableton-guide rule 2)
READ_PER_CALL = 20


@dataclass
class LiveOps:
    """Steps against one Live. `staging` is the folder the Save panel writes exports into before they move to their
    target: one the panel can reach (hands.live.export.SavePanel). Without it, `export` refuses."""

    client: McpTransport
    staging: Path | None = None
    save_panel: gui_export.SavePanel = field(default_factory=gui_export.SavePanel)

    def run(self, code: str) -> Any:
        """One LOM call: an expression, or statements that set `result`."""
        return self.client.run(code)

    def guard(self, where: str) -> str:
        """hands' session guard: no dialog, one of our sets in front, the LOM answering. Returns the front set."""
        return session.check(self.client, where)

    def setp(self, device: str, params: dict[str, Any]) -> None:
        """Set a device's parameters (`device` is a LOM expression), in the units Live shows ("-6 dB", "Saw D") or
        as raw numbers, 16 to a call. Stops on a parameter the device lacks or a value it cannot show."""
        items = list(params.items())
        for k in range(0, len(items), PER_CALL):
            code = (
                f"d = {device}\nps = {{}}\nfor p in d.parameters:\n    ps.setdefault(p.name, p)\nbad = []\n"
                + "".join(
                    f"bad.append(set_shown(ps[{n!r}], {v!r}, {n!r}) if {n!r} in ps else {n + '?'!r})\n"
                    for n, v in items[k : k + PER_CALL]
                )
                + "result = [b for b in bad if b]"
            )
            missing = self.run(with_source(code, "shown"))
            if missing:
                stop(f"{device}: {missing}")

    def mixer(
        self, track: str, vol_db: float | None = None, sends: tuple[float | None, ...] = (), pan: float | None = None
    ) -> None:
        """A track's volume (dB), sends (dB by return index, None for off) and pan (-1..1), in one call."""
        lines = [f"m = {track}.mixer_device", "bad = []"]
        if vol_db is not None:
            lines.append(f"bad.append(set_shown(m.volume, '{vol_db} dB', 'volume'))")
        for k, s in enumerate(sends):
            lines.append(
                f"m.sends[{k}].value = 0.0" if s is None else f"bad.append(set_shown(m.sends[{k}], '{s} dB', 'send'))"
            )
        if pan is not None:
            lines.append(f"m.panning.value = {float(pan)}")
        lines.append("result = [b for b in bad if b]")
        bad = self.run(with_source("\n".join(lines), "shown"))
        if bad:
            stop(f"{track} mixer: {bad}")

    def params(self, device: str, names: list[str] | None = None, start: int = 0, count: int = 20) -> list:
        """Up to 20 parameters of a device: [name, shown, raw (rounded to 4 places)]."""
        pick = (
            f"[p for p in d.parameters if p.name in {names!r}]"
            if names
            else f"list(d.parameters)[{start}:{start + min(count, READ_PER_CALL)}]"
        )
        return self.run(
            f"d = {device}\nresult = [(p.name, p.str_for_value(p.value), round(p.value, 4)) for p in {pick}]"
        )

    def load_item(self, track: str, root: str, folder: str | None, name: str) -> None:
        """Load a browser item (a device, a preset or a sample) onto `track` (a LOM expression). `folder` is a child of
        browser.<root> (e.g. "Mallets" under sounds), or None for an item at the top of the root."""
        where = f"[x for x in browser.{root}.children if x.name == {folder!r}][0]" if folder else f"browser.{root}"
        self.select_track(track)
        self.run(
            f"c = {where}\nit = [x for x in c.children if x.name == {name!r}]\n"
            f"if not it: raise ValueError('no ' + {name!r})\nbrowser.load_item(it[0])\ntime.sleep(0.3)\n"
            "result = 'requested'"
        )
        time.sleep(1.0)

    def select_track(self, track: str) -> None:
        """Select `track` and read the selection back: setting it can silently not take (Main right after a view
        change), and a load would then land on whatever track was selected."""
        for _ in range(4):
            self.run(f"song.view.selected_track = {track}\nresult = 'ok'")
            time.sleep(0.2)
            if self.run(f"result = song.view.selected_track.name == {track}.name"):
                return
            self.run(
                "song.view.selected_track = song.return_tracks[0] if len(song.return_tracks) else song.tracks[0]\n"
                "result = 'ok'"
            )
            time.sleep(0.2)
        stop(f"could not select {track}")

    def devices(self, track: str) -> list[str]:
        """The names of a track's devices, in chain order."""
        return self.run(f"result = [d.name for d in {track}.devices]")

    def export(
        self, out: Path, start_beat: float, length_beats: float, *, bits: int = 24, timeout_s: float = 300
    ) -> Path:
        """Render Main for [start_beat, start_beat + length_beats) to `out` by the menu (hands.live.export)."""
        if self.staging is None:
            raise ValueError("this LiveOps has no staging folder for exports; give it one the Save panel can reach")
        return gui_export.export_by_menu(
            self.client,
            out,
            start_beat,
            length_beats,
            staging=self.staging,
            bits=bits,
            timeout_s=timeout_s,
            panel=self.save_panel,
        )

    def save_as(self, folder: Path, name: str, *, project: bool = True, timeout_s: float = 60) -> Path:
        """File > Save Live Set As (hands.live.export.save_as)."""
        return gui_export.save_as(folder, name, project=project, panel=self.save_panel, timeout_s=timeout_s)
