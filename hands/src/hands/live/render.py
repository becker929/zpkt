"""Render the arrangement to files through Live's Export Audio/Video dialog: the one export path.

export_audio.applescript (package data) drives the dialog and the Save panel: it sets the rendered
track, file type, bit depth and sample rate, turns MP3 off, types the file name and waits for the
file. The range is the arrangement's time selection, made by timeops.select, so the script never
types into the range sliders. An export costs about 13 s plus 0.1 s per second of audio, most of
the fixed part the dialog's own waiting (docs/probe-packing-findings.md).

Real-time takes through a resampling track are in hands.live.record; checks on the written audio
are in hands.audio.
"""

from __future__ import annotations

import time
from pathlib import Path

from hands import steps
from hands.live import timeops, ui
from hands.live.session import stop
from hands.live.transport import McpTransport

SCRIPT = Path(__file__).with_name("export_audio.applescript")
FILE_TYPES = {".wav": "WAV", ".aif": "AIFF", ".aiff": "AIFF", ".flac": "FLAC"}


def export(client: McpTransport, out: Path, start_beat: float | None = None, length_beats: float | None = None,
           *, mode: str = "Main", bits: int = 32, sample_rate: int = 44100, tries: int = 2) -> list[Path]:
    """Export [start_beat, start_beat + length_beats) and return the files Live wrote.

    Without a range the dialog keeps Live's own: the loop brace if set, else the whole song.
    `mode` is "Main", a track's name (Live adds " <name>" to the file name), "All Individual
    Tracks" or "Selected Tracks Only" (one file per track, `out` as the prefix).

    The target must be new: exporting over files makes Live trash the old ones and rename the new
    ones. If the script fails but the files landed and no dialog is left, that is a success (the
    error comes from the window-closing race); it retries only when nothing was written. The
    pointer is parked afterwards, since the script clicks the Save panel with cliclick.
    """
    out = Path(out).absolute()
    if out.suffix.lower() not in FILE_TYPES:
        raise ValueError(f"{out.name}: export writes {sorted(FILE_TYPES)}")
    if (start_beat is None) != (length_beats is None):
        raise ValueError("give both start_beat and length_beats, or neither")
    out.parent.mkdir(parents=True, exist_ok=True)
    if any(f.name.startswith(out.stem) for f in out.parent.iterdir()):
        stop(f"export: target not empty, {out.stem}* already in {out.parent}")
    args = [str(out), FILE_TYPES[out.suffix.lower()], str(bits), str(sample_rate), "0", mode, "-1"]
    error = ""
    try:
        for _ in range(tries):
            t0 = time.time()
            if start_beat is not None and length_beats is not None:
                timeops.select(client, start_beat, length_beats)
            steps.report(f"export {out.name}: the Export dialog", "minor")
            try:
                ui.osa_file(SCRIPT, *args, timeout=900)
                ok = True
            except ui.UiError as exc:
                ok, error = False, str(exc)[-400:]
            written = _written(out, since=t0 - 1)
            if written and ok:
                _wait_for_dialogs_to_close(written)
            elif written:  # the script erred, but the render landed
                time.sleep(3)
                if ui.dialogs():
                    ui.close_dialogs()
                if ui.dialogs():
                    stop(f"export: wrote {len(written)} file(s) but a dialog stayed open: {error}")
                steps.timing("export_script_error_files_ok", time.time() - t0, files=len(written), err=error[-120:])
            if written:
                steps.report(f"exported {', '.join(f.name for f in written)}", "major")
                return written
            ui.close_dialogs()
            if ui.dialogs():
                stop(f"export: failed and a dialog stayed open: {error}")
        stop(f"export: nothing written after {tries} tries: {error}")
    finally:
        ui.park_cursor()


def _written(out: Path, since: float) -> list[Path]:
    """Files of this export: named like `out` (Live may add a track name), new since `since`."""
    return sorted(f for f in out.parent.iterdir()
                  if f.name.startswith(out.stem) and f.suffix == out.suffix and f.stat().st_mtime >= since)


def _wait_for_dialogs_to_close(written: list[Path], timeout_s: float = 60.0) -> None:
    """The progress and Export windows close a moment after the file lands."""
    deadline = time.monotonic() + timeout_s
    while ui.dialogs():
        if time.monotonic() > deadline:
            stop(f"export: wrote {len(written)} file(s) but a dialog stayed open for {timeout_s:g} s")
        time.sleep(0.5)
