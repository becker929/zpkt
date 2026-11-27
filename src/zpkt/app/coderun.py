"""Code for Live, made ready to send: a proposal's code step, or an ability, with the abilities it uses.

`prepare` reads the code (never runs it) and answers with the one text to send, or with why it cannot be sent:

- it must parse as Live's Python does (3.11);
- the rails: code is screened for the names it spells out, a monitor track's ("mon ...") and the two devices that
  are only the desk's own on Main. Arguments that are text are screened the same way (`screened_args`), also inside
  Live when one ability hands them to another. This guards against an accident; it is not a wall;
- every `use("name", {...})` must name an ability that is there, with no circle and no chain deeper than
  zpkt.app.abilities.MAX_DEPTH, and arguments that are written out must fit the ability's parameters.

What is sent is `abilities.program`: the arguments and the used abilities' code as one JSON literal, `use` and
`args` defined, then the code. It is one call to Live, under the bus's lock, as `live.run` is (zpkt.app.jobs).
`Prepared.reads` says the code and everything it uses only read (zpkt.live.agent.only_reads, the test `live.read`
uses): such a run leaves no History row.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from zpkt.app import abilities
from zpkt.live import monitor_tracks
from zpkt.live.agent import only_reads

LIVE_PYTHON = (3, 11)  # Live's own Python: code is parsed as that version reads it, as far as `ast` can tell
RESULT_MAX = 1000  # characters of a result kept in a reply
# The devices that are only the desk's own on Main: code that names one is refused. (Main's "desk Glue" has
# namesakes on the buses, so a name alone does not say which is meant.)
ONLY_ON_MAIN = ("zpkt listen", "zpkt desk meter")


@dataclass(frozen=True)
class Prepared:
    """Code ready to send."""

    program: str  # the text of the one call
    uses: list[str]  # every ability sent along with it, the ones it names first
    reads: bool  # it, and all it uses, only read


def screened(tree: ast.AST) -> str | None:
    """Why the rails hold this code, by the names it spells out, or None. A guard against accidents, not a wall."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if node.value.casefold().startswith(monitor_tracks.PREFIX):
            return f'the code names "{node.value}": that is a monitor track, and the app never changes those'
        if node.value in ONLY_ON_MAIN:
            return f'the code names "{node.value}", one of the desk\'s own devices on Main: the app never changes those'
    return None


def screened_args(args: Mapping[str, Any]) -> str | None:
    """Why the rails hold these arguments, or None: a text value is screened as a name the code spells out is."""
    for name, value in args.items():
        if not isinstance(value, str):
            continue
        if value.casefold().startswith(monitor_tracks.PREFIX):
            return f'{name} is "{value}": that is a monitor track, and the app never changes those'
        if value in ONLY_ON_MAIN:
            return f'{name} is "{value}", one of the desk\'s own devices on Main: the app never changes those'
    return None


def parsed(code: str) -> ast.AST | str:
    """The code as Live's Python reads it, or why it cannot be sent: it does not parse, or the rails hold it."""
    try:
        tree = ast.parse(code, feature_version=LIVE_PYTHON)
    except SyntaxError as exc:
        return f"is not Python that parses: {exc.msg} (line {exc.lineno})"
    return screened(tree) or tree


def literals(tree: ast.AST) -> list[str]:
    """The text the code spells out, each once."""
    found = (n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return list(dict.fromkeys(found))


def prepare(
    code: str, args: Mapping[str, Any], library: Mapping[str, Mapping[str, Any]], top: str = ""
) -> Prepared | str:
    """The code made ready, or why it cannot be sent. `library` is every ability by name; `top` is the name of the
    ability this code is, or would be kept as (it may not be used by what it uses)."""
    tree = parsed(code)
    if isinstance(tree, str):
        return tree
    found = abilities.calls(tree)
    if isinstance(found, str):
        return found
    for name, written in found:
        if name in library and written is not None:
            why = abilities.args_problem(library[name].get("params") or {}, written) or screened_args(written)
            if why:
                return f'use("{name}"): {why}'
    reach = abilities.closure([name for name, _ in found], library, top)
    if isinstance(reach, str):
        return reach
    for name in reach:
        inner = parsed(str(library[name]["code"]))
        if isinstance(inner, str):
            return f'the ability "{name}" cannot be used: its code {inner}'
    lib = {name: library[name] for name in reach}
    reads = only_reads(code) and all(only_reads(str(a["code"])) for a in lib.values())
    text = abilities.program(code, args, lib, monitor_tracks.PREFIX, ONLY_ON_MAIN)
    return Prepared(text, reach, reads)


def brief(result: Any) -> Any:
    """A result, small enough for a reply."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return result if len(text) <= RESULT_MAX else text[:RESULT_MAX] + "…"
