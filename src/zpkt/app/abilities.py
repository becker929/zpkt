"""Abilities: code for Live that you allowed an agent to run for good, kept one file each.

Anthony, 26 November 2026: "in addition to approve, an 'Always' button which adds the code to an auto allowed set, as
new abilities with documentation and everything, run the same as other tools." And: "Guide the agent to write
functions with clean parameters for the new tools so that we don't proliferate lots of dumb tools. Also allow the
agent to chain tools together so we build abstraction over time."

An ability is a code step of a proposal (`live.propose`, zpkt.app.propose) that you answered with "Always": its name,
what it does in one sentence, its parameters, and the code exactly as the card showed it. From then on an agent may
run it with no card and no wait (`ability.run`, or a `use` step in a batch); the standing yes is that tap. What stays
true:

- The code is the code you saw. The app never edits an ability in place: a changed version is a new proposal and a
  new tap, and it takes the old one's place only after "Always" on the new card.
- What varies between runs is the arguments. They are data: the app checks them against the declared parameters
  (type, `enum`; a parameter without a `default` is required) and hands them to the code as a dict called `args`,
  made from a JSON literal in the same call. They are never formatted into the code's text (`program`).
- Abilities build on each other: in code, `use("other_ability", {...})` runs another one and gives back its
  `result`. The name must be written out, so the app can see what a piece of code uses by reading it (`calls`), send
  exactly those abilities along in the same one call (`closure`, `program`), and refuse beforehand an unknown name,
  a cycle, a chain deeper than MAX_DEPTH, and arguments written out that do not fit. Each one used runs in a
  namespace of its own, with its own `args` and the same Live names.
- Removing one is immediate (`Store.remove`): the next call finds nothing, and an ability that used it is broken
  until the missing one is proposed again. The file is moved to `removed/` beside the others, so the code is not lost.

One JSON file per ability, <folder>/<name>.json (lib/contracts/ability.schema.json): "name", "does", "params"
({name: {"type", "description", "default"?, "enum"?}}), "code", "made" (when, UTC), "session" (the chat it came
from), "runs", "last_run". The folder is a rig setting (`abilities_dir`, default <sets_dir>/abilities): an ability
is code for Live in general, not for one set.

This module is the store and the rules: names, parameters, arguments, what uses what, and the text that is sent to
Live. It does not talk to Live and imports nothing that does; zpkt.app.coderun sends, and the commands are in
zpkt.app.propose and zpkt.app.change.
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

MAX = 50  # abilities kept at once
MAX_PARAMS = 8
MAX_ENUM = 20
MAX_DEPTH = 5  # abilities used by abilities, at most this deep
MAX_USED = 12  # abilities sent along with one call
DESCRIPTION_MAX = 200  # characters of a parameter's description
STRING_MAX = 200  # characters of a string argument
NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
NAME_RULE = "snake_case: a small letter, then small letters, digits and _ (at most 40 characters)"
TYPES = ("number", "integer", "string", "boolean")
ARGS_MAX = 60  # characters of the arguments in a History row or a card
TOOL_PREFIX = "ability_"  # an ability's tool is named ability_<name>: none of the built-in tools starts so
Params = dict[str, dict[str, Any]]


class Full(RuntimeError):
    """There are MAX abilities already: one has to go before another is kept."""


# ---- names ---------------------------------------------------------------------------------------------------------


def slug(does: str) -> str:
    """A name made from a sentence: "Sets the tempo to 91." is "sets_the_tempo_to_91"."""
    text = re.sub(r"[^a-z0-9]+", "_", does.lower()).strip("_")[:40].strip("_")
    return text if NAME.match(text) else ("do_" + text)[:40].strip("_") if text else "ability"


def free_name(base: str, taken: Iterable[str]) -> str:
    """`base`, or `base_2`, `base_3`... when it is taken."""
    have = set(taken)
    if base not in have:
        return base
    n = 2
    while f"{base[: 40 - len(str(n)) - 1]}_{n}" in have:
        n += 1
    return f"{base[: 40 - len(str(n)) - 1]}_{n}"


def near(name: str, does: str, have: Iterable[Mapping[str, Any]]) -> str | None:
    """The name of an ability that looks like this one under another name: the names differ only by an ending, or
    the sentences are the same. None when there is none (an ability of the same name is the one being replaced)."""
    same = " ".join(does.lower().split()).rstrip(".")
    for a in have:
        other = str(a["name"])
        if other == name:
            continue
        if name.startswith(other + "_") or other.startswith(name + "_"):
            return other
        if " ".join(str(a.get("does", "")).lower().split()).rstrip(".") == same:
            return other
    return None


# ---- parameters and arguments ------------------------------------------------------------------------------------


def _is(kind: str, value: Any) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str) and len(value) <= STRING_MAX
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
        return False
    return kind == "number" or float(value) == int(value)


def read_params(raw: Any) -> Params | str:
    """Declared parameters as {name: {"type", "description", "default"?, "enum"?}}, or what is wrong with them.
    None is no parameters."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return '"params" is an object: {"<name>": {"type": "number", "description": "..."}}'
    if len(raw) > MAX_PARAMS:
        return f"{len(raw)} parameters is more than {MAX_PARAMS}"
    out: Params = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not NAME.match(name):
            return f'the parameter name "{name}" is not {NAME_RULE}'
        if not isinstance(spec, dict) or spec.get("type") not in TYPES:
            return f'the parameter "{name}" needs "type": one of {", ".join(TYPES)}'
        kind = spec["type"]
        text = spec.get("description")
        if not isinstance(text, str) or not text.strip():
            return f'the parameter "{name}" needs "description": what it is and its unit, for whoever runs it later'
        if len(text) > DESCRIPTION_MAX:
            return f'the description of "{name}" is {len(text)} characters, more than {DESCRIPTION_MAX}'
        one: dict[str, Any] = {"type": kind, "description": " ".join(text.split())}
        if "enum" in spec:
            choices = spec["enum"]
            if not isinstance(choices, list) or not 1 <= len(choices) <= MAX_ENUM or kind == "boolean":
                return f'the "enum" of "{name}" is a list of 1 to {MAX_ENUM} values (not for a boolean)'
            if not all(_is(kind, c) for c in choices):
                return f'every value in the "enum" of "{name}" must be a {kind}'
            one["enum"] = list(choices)
        if "default" in spec:
            if not _is(kind, spec["default"]) or ("enum" in one and spec["default"] not in one["enum"]):
                return f'the "default" of "{name}" must be a {kind}' + (" from its enum" if "enum" in one else "")
            one["default"] = spec["default"]
        out[name] = one
    return out


def signature(params: Params) -> str:
    """ "track: string, amount: number = 0.5": the parameters in a line."""
    return ", ".join(
        f"{name}: {p['type']}" + (f" = {json.dumps(p['default'])}" if "default" in p else "")
        for name, p in params.items()
    )


def args_problem(params: Params, args: Any) -> str | None:
    """Why `args` are not values for `params`, or None. A parameter without a default is required, and nothing
    that is not a parameter is taken."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return '"args" is an object: a value for each parameter'
    missing = [name for name, p in params.items() if name not in args and "default" not in p]
    if missing:
        return f"args lacks {', '.join(missing)} ({signature(params)})"
    unknown = [str(name) for name in args if name not in params]
    if unknown:
        known = signature(params) if params else "it takes no parameters"
        return f"args has {', '.join(unknown)}, which is not a parameter ({known})"
    for name, p in params.items():
        if name not in args:
            continue
        if not _is(p["type"], args[name]):
            limit = f" of at most {STRING_MAX} characters" if p["type"] == "string" else ""
            return f"{name} must be a {p['type']}{limit}, not {json.dumps(args[name], default=str)[:40]}"
        if "enum" in p and args[name] not in p["enum"]:
            return f"{name} must be one of {json.dumps(p['enum'])}, not {json.dumps(args[name])[:40]}"
    return None


def typed(params: Params, args: Mapping[str, Any] | None) -> dict[str, Any]:
    """`args` in the parameters' order with the defaults filled in, an integer as an int (JSON may bring 3.0)."""
    given = args or {}
    out = {}
    for name, p in params.items():
        value = given[name] if name in given else p["default"]
        out[name] = int(value) if p["type"] == "integer" else value
    return out


def call_words(name: str, args: Mapping[str, Any]) -> str:
    """ "send_to_drive(track="hats", amount=0.5)": a run in a few words, for a History row and a card."""
    inside = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    if len(inside) > ARGS_MAX:
        inside = inside[: ARGS_MAX - 1] + "…"
    return f"{name}({inside})"


# ---- reading code: which parameters it reads, which abilities it uses -------------------------------------------


def _key(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def reads(tree: ast.AST) -> set[str]:
    """The parameters the code reads: every `args["x"]` and `args.get("x")` with the name written out."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "args":
            key = _key(node.slice)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "args"
            and node.args
        ):
            key = _key(node.args[0])
        else:
            continue
        if key is not None:
            found.add(key)
    return found


def calls(tree: ast.AST) -> list[tuple[str, dict[str, Any] | None]] | str:
    """The abilities the code uses, in order: (name, the arguments when they are written out as a literal, else
    None). A `use(...)` whose name is not written out is the problem returned: the app must be able to read what
    will run."""
    out: list[tuple[str, dict[str, Any] | None]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "use"):
            continue
        name = _key(node.args[0]) if node.args else None
        if name is None or len(node.args) > 2 or node.keywords:
            return 'use() takes the ability\'s name written out, then its arguments: use("ability_name", {...})'
        literal = None
        if len(node.args) == 2:
            with contextlib.suppress(ValueError, SyntaxError):
                value = ast.literal_eval(node.args[1])
                literal = value if isinstance(value, dict) else None
        else:
            literal = {}
        out.append((name, literal))
    return out


def used(code: str) -> list[str]:
    """The names of the abilities a piece of code uses, each once, in order; none for code that does not read."""
    try:
        found = calls(ast.parse(code))
    except SyntaxError:
        return []
    return list(dict.fromkeys(name for name, _ in found)) if isinstance(found, list) else []


def closure(first: list[str], library: Mapping[str, Mapping[str, Any]], top: str = "") -> list[str] | str:
    """Every ability that running code which uses `first` may reach, each once, or why it cannot be run: one is
    not there, they go round in a circle, the chain is deeper than MAX_DEPTH, or there are more than MAX_USED.
    `top` is the name of the ability the code itself is (or would be kept as), which closes a circle too."""
    order: list[str] = []

    def walk(name: str, path: tuple[str, ...]) -> str | None:
        if name in path or name == top:
            return "abilities may not use each other in a circle: " + " uses ".join(
                [*path, name] if path else [top, name]
            )
        if name not in library:
            by = f' (used by "{path[-1]}")' if path else ""
            return f'there is no ability "{name}"{by}: it was removed or never kept, and can be proposed again'
        if len(path) + 1 > MAX_DEPTH:
            return f"abilities are chained deeper than {MAX_DEPTH}: {' uses '.join([*path, name])}"
        if name not in order:
            order.append(name)
        for inner in used(str(library[name]["code"])):
            if why := walk(inner, (*path, name)):
                return why
        return None

    for name in dict.fromkeys(first):
        if why := walk(name, ()):
            return why
    if len(order) > MAX_USED:
        return f"that uses {len(order)} abilities in one call, more than {MAX_USED}"
    return order


def graph(found: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """For every ability: what it "uses", what it is "used_by", and what it uses that is "missing" (it is broken
    until those are proposed again, whether it names them itself or through another)."""
    have = {str(a["name"]): a for a in found}
    uses = {name: used(str(a["code"])) for name, a in have.items()}
    out = {}
    for name in have:
        reach = closure(uses[name], have, top=name)
        gone = sorted({n for n in _reach(name, uses) if n not in have}) if isinstance(reach, str) else []
        out[name] = {
            "uses": uses[name],
            "used_by": sorted(other for other, inner in uses.items() if name in inner),
            "missing": gone,
        }
    return out


def _reach(name: str, uses: Mapping[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    todo = list(uses.get(name, []))
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += uses.get(n, [])
    return seen


# ---- what is sent to Live ------------------------------------------------------------------------------------------

# Defined in front of code that uses abilities. `_zp` is data (a JSON literal): the arguments, the code and
# parameters of every ability that may be used, and the names the rails hold. Stdlib only, Python 3.11.
_USE = """_zp_base = dict(globals())
def use(name, args=None):
    a = _zp["lib"].get(name)
    if a is None:
        raise LookupError("use(%r): that ability was not sent with this call; write its name out, use('name', {...})" % (name,))
    if _zp["depth"] <= 0:
        raise RuntimeError("use(%r): abilities are chained too deep" % (name,))
    given, vals = dict(args or {}), {}
    for k, p in a["params"].items():
        if k in given:
            v = given.pop(k)
        elif "default" in p:
            v = p["default"]
        else:
            raise TypeError("use(%r): it needs %s" % (name, k))
        t = p["type"]
        if t == "boolean":
            ok = isinstance(v, bool)
        elif t == "string":
            ok = isinstance(v, str)
        else:
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and (t == "number" or v == int(v))
        if not ok or ("enum" in p and v not in p["enum"]):
            raise TypeError("use(%r): %s must be a %s%s, not %r" % (name, k, t, " of %r" % (p["enum"],) if "enum" in p else "", v))
        if isinstance(v, str) and (v.lower().startswith(_zp["prefix"]) or v in _zp["names"]):
            raise ValueError("use(%r): %s is %r, and the app never changes that" % (name, k, v))
        vals[k] = int(v) if t == "integer" else v
    if given:
        raise TypeError("use(%r): %s is not one of its parameters" % (name, ", ".join(sorted(given))))
    ns = dict(_zp_base)
    ns["use"], ns["args"] = use, vals
    ns.pop("result", None)
    _zp["depth"] -= 1
    try:
        exec(a["code"], ns)
    finally:
        _zp["depth"] += 1
    return ns.get("result")
"""


def program(
    code: str,
    args: Mapping[str, Any],
    lib: Mapping[str, Mapping[str, Any]] | None = None,
    prefix: str = "",
    names: Iterable[str] = (),
) -> str:
    """The text of one call to Live: `args` defined, then the code. With `lib` (the abilities the code may use,
    {name: {"code", "params"}}), `use` is defined too, and `prefix` and `names` are what the rails hold in a text
    argument. Every value goes in as a JSON literal that Live parses: it is data, and no character of an argument
    becomes code."""
    if not lib:
        return f"args = __import__('json').loads({json.dumps(dict(args))!r})\n{code}"
    data = {
        "args": dict(args),
        "lib": {n: {"code": a["code"], "params": a.get("params") or {}} for n, a in lib.items()},
        "prefix": prefix,
        "names": list(names),
        "depth": MAX_DEPTH,
    }
    return f"_zp = __import__('json').loads({json.dumps(data)!r})\n{_USE}args = _zp[\"args\"]\n{code}"


# ---- the store -----------------------------------------------------------------------------------------------------


def stamp(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


class Store:
    """The abilities on disk. Every method reads the folder afresh: a file a person takes away is gone at once."""

    def __init__(self, folder: Path, clock: Callable[[], float] = time.time) -> None:
        self.folder, self.clock = Path(folder), clock
        self.lock = threading.Lock()

    def _file(self, name: str) -> Path:
        return self.folder / f"{name}.json"

    def _read(self, file: Path) -> dict[str, Any] | None:
        """One ability, or None for a file that is not one (it is passed over, never guessed at)."""
        try:
            a = json.loads(file.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(a, dict) or a.get("name") != file.stem or not NAME.match(file.stem):
            return None
        if not isinstance(a.get("code"), str) or not isinstance(a.get("does"), str):
            return None
        params = read_params(a.get("params"))
        if isinstance(params, str):
            return None
        return {**a, "params": params}

    def all(self) -> list[dict[str, Any]]:
        """Every ability, by name."""
        if not self.folder.is_dir():
            return []
        found = (self._read(f) for f in sorted(self.folder.glob("*.json")))
        return [a for a in found if a is not None]

    def names(self) -> list[str]:
        return [a["name"] for a in self.all()]

    def library(self) -> dict[str, dict[str, Any]]:
        """Every ability by its name: what `use` may reach."""
        return {a["name"]: a for a in self.all()}

    def get(self, name: Any) -> dict[str, Any] | None:
        if not isinstance(name, str) or not NAME.match(name):
            return None
        return self._read(self._file(name))

    def _write(self, a: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f".{a['name']}.json.tmp"
        tmp.write_text(json.dumps(a, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, self._file(a["name"]))

    def save(self, name: str, does: str, params: Params, code: str, session: str = "") -> tuple[dict[str, Any], bool]:
        """Keep a code step as the ability `name`: (the ability, whether it took the place of an older one of that
        name). Full when there are MAX already and this would be one more."""
        if not NAME.match(name):
            raise ValueError(f"an ability's name is {NAME_RULE}, not {name!r}")
        with self.lock:
            old = self._read(self._file(name))
            if old is None and len(self.all()) >= MAX:
                raise Full(f"there are {MAX} abilities already: remove one first")
            a = {
                "name": name,
                "does": does,
                "params": params,
                "code": code,
                "made": stamp(self.clock()),
                "session": session,
                "runs": 0,
                "last_run": None,
            }
            self._write(a)
            return a, old is not None

    def ran(self, name: str) -> None:
        """Count a run. An ability that went away meanwhile is left gone."""
        with self.lock:
            a = self._read(self._file(name))
            if a is not None:
                a["runs"] = int(a.get("runs") or 0) + 1
                a["last_run"] = stamp(self.clock())
                self._write(a)

    def remove(self, name: Any) -> bool:
        """Take the standing yes back, at once. True when there was such an ability. The file is kept in removed/."""
        with self.lock:
            if self.get(name) is None:
                return False
            gone = self.folder / "removed"
            gone.mkdir(parents=True, exist_ok=True)
            when = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.clock()))
            with contextlib.suppress(OSError):
                os.replace(self._file(name), gone / f"{name}-{when}.json")
            with contextlib.suppress(OSError):
                self._file(name).unlink()  # if the move did not work, it still must be gone
            return True
