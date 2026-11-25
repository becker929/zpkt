"""The `zpkt` command: `zpkt live ...` is `hands ...`, `zpkt audio ...` is `ears ...`; `zpkt app` starts the app.

`zpkt live ping` is short for `zpkt live live ping`: hands keeps the commands that talk to the open set in a group
of its own, also named `live`, and nobody should have to say the word twice.

Each half is imported only when asked for, so `zpkt live` runs where only zpkt[live] is installed.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Collection, Mapping

USAGE = """usage: zpkt COMMAND [ARGS]...

  live    drive Ableton Live (the same commands as `hands`)
  audio   measure renders (the same commands as `ears`; the meters also as `mlab`)
  app     the one interface: the mix desk and the /app/ shell, the only door to Live
  page    make or check a page of controls (an agent hands the running app a spec)

`zpkt live --help` and `zpkt audio --help` list each one's commands."""


def live_args(args: list[str], commands: Collection[str], live_commands: Collection[str]) -> list[str]:
    """The arguments `hands` gets for `zpkt live ARGS`. A first word that is a command of hands' `live` group, and
    not a command of hands itself, gets `live` put before it."""
    if args and args[0] in live_commands and args[0] not in commands:
        return ["live", *args]
    return args


def plain_help(stdout_is_tty: bool, env: Mapping[str, str]) -> bool:
    """True when --help should be plain text: Rich's boxed panels are token padding for a pipe or NO_COLOR."""
    return not stdout_is_tty or bool(env.get("NO_COLOR"))


def use_plain_help() -> None:
    """Turn Rich help off for this process when output is piped or NO_COLOR is set. Call before the CLI runs."""
    if not plain_help(sys.stdout.isatty(), os.environ):
        return
    os.environ.setdefault("TYPER_USE_RICH", "0")
    import typer.core

    typer.core.HAS_RICH = False


def live_invocation(
    args: list[str], commands: Collection[str], live_commands: Collection[str]
) -> tuple[list[str], str]:
    """The arguments `hands` gets for `zpkt live ARGS`, and the program name to show in usage. A command of hands'
    `live` group gets `live` put before it and the name `zpkt`, so its usage reads `zpkt live state`, not
    `zpkt live live state`; any other command is shown as `zpkt live ...`."""
    full = live_args(args, commands, live_commands)
    return (full, "zpkt") if full != args else (full, "zpkt live")


def main() -> None:
    args = sys.argv[1:]
    part = args[0] if args else ""
    if part not in ("live", "audio", "app", "page"):
        print(USAGE)
        sys.exit(0 if part in ("", "-h", "--help") else 2)
    sys.argv = [f"zpkt {part}", *args[1:]]
    use_plain_help()
    if part == "app":
        from zpkt.app import main as app_main

        app_main()
        return
    if part == "page":
        from zpkt.app.page_cli import main as page_main

        page_main()
        return
    if part == "live":
        import typer

        from zpkt.live.cli import app as live_app
        from zpkt.live.cli import main as live_main

        hands = typer.main.get_group(live_app)
        live_group = hands.commands["live"]
        rest, prog = live_invocation(args[1:], list(hands.commands), list(getattr(live_group, "commands", {})))
        live_main(rest, prog)
        return
    try:
        from zpkt.audio.cli import main as audio_main
    except ImportError as exc:
        sys.exit(f"zpkt audio needs the audio extra ({exc.name} is missing): install zpkt[audio].")
    audio_main()


if __name__ == "__main__":
    main()
