"""The `zpkt` command: `zpkt live ...` is `hands ...`, `zpkt audio ...` is `ears ...`.

Each half is imported only when asked for, so `zpkt live` runs where only zpkt[live] is installed.
"""

from __future__ import annotations

import sys

USAGE = """usage: zpkt COMMAND [ARGS]...

  live    drive Ableton Live (the same commands as `hands`)
  audio   measure renders (the same commands as `ears`; the meters also as `mlab`)

`zpkt live --help` and `zpkt audio --help` list each one's commands."""


def main() -> None:
    args = sys.argv[1:]
    part = args[0] if args else ""
    if part not in ("live", "audio"):
        print(USAGE)
        sys.exit(0 if part in ("", "-h", "--help") else 2)
    sys.argv = [f"zpkt {part}", *args[1:]]
    if part == "live":
        from zpkt.live.cli import main as live_main

        live_main()
        return
    try:
        from zpkt.audio.cli import main as audio_main
    except ImportError as exc:
        sys.exit(f"zpkt audio needs the audio extra ({exc.name} is missing): install zpkt[audio].")
    audio_main()


if __name__ == "__main__":
    main()
