"""`zpkt page make|lint SPEC`: an agent hands the running app a Page spec and is told what came of it.

The spec is a JSON file (or `-` for standard input). The app lints it against the open set. `make` also saves it and
puts it on the desk and the MiniLab. The command goes to the app's API (ZPKT_APP_URL) with the agent's token, so the app
stamps it who=agent and the agent rule applies. A rejected spec prints the reasons and exits 1, so the agent can repair it and try again.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from zpkt.app.client import DEFAULT_URL, AppClient, app_url


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="zpkt page", description="Make or check a page of controls for the open set.")
    p.add_argument("action", choices=["make", "lint"], help="make: lint, save and put on the desk. lint: check only.")
    p.add_argument("spec", help="a Page spec (.json), or - for standard input")
    p.add_argument("--prompt", help="what was asked for, kept with the page")
    p.add_argument("--no-apply", action="store_true", help="save the page but do not put it on the desk")
    p.add_argument("--url", default=app_url(), help=f"the app's API (ZPKT_APP_URL, default {DEFAULT_URL})")
    p.add_argument("--json", action="store_true", dest="as_json", help="print the app's whole answer as JSON")
    return p.parse_args(list(argv))


def read_spec(source: str, stdin: TextIO) -> Any:
    text = stdin.read() if source == "-" else open(source).read()  # noqa: SIM115  (a short read)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SystemExit(f"{source} is not JSON ({exc}). Write the page spec as one JSON object.") from None


def say(code: int, reply: dict[str, Any], action: str, out: TextIO) -> int:
    """Print what came of it; 0 when it worked."""
    if code != 200:
        print(reply.get("error", f"The app answered {code}."), file=out)
        for p in reply.get("problems", []):
            print(f"{p['level']}: {p['where']}: {p['text']}", file=out)
        return 1
    for p in reply.get("problems", []):
        print(f"{p['level']}: {p['where']}: {p['text']}", file=out)
    if action == "make":
        where = f", on the desk as page {reply['pages'][0] + 1}" if reply.get("pages") else ""
        print(f"made {reply['title']!r} as {reply['id']}{where}", file=out)
    else:
        print("ok" if reply.get("ok") else "not shown: fix the errors", file=out)
    return 0 if reply.get("ok") else 1


def run(argv: Sequence[str], stdin: TextIO = sys.stdin, out: TextIO = sys.stdout) -> int:
    args = parse_args(argv)
    spec = read_spec(args.spec, stdin)
    cmd_args: dict[str, Any] = {"spec": spec}
    if args.prompt:
        cmd_args["prompt"] = args.prompt
    if args.no_apply:
        cmd_args["apply"] = False
    try:
        code, reply = AppClient("agent", url=args.url).submit(f"page.{args.action}", cmd_args)
    except OSError as exc:
        print(f"The app does not answer at {args.url} ({exc}). Start it with `zpkt app`.", file=out)
        return 2
    if args.as_json:
        print(json.dumps(reply, indent=1), file=out)
        return 0 if code == 200 and reply.get("ok", True) else 1
    return say(code, reply, args.action, out)


def main() -> None:
    sys.exit(run(sys.argv[1:]))
