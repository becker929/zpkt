"""`hands doctor`: is this Mac's rig where hands will look for it?

Reads the rig config (hands.config) and checks, without changing anything, that its folders
exist, that the probe kits in <data_dir>/kits have their sets in sets_dir under one of our
prefixes, that Live is installed, and (unless asked not to) that Live answers and which set is in
front. Every problem says what is missing and where it was looked for, so a missing rig.toml
shows up as "no kits in ~/Music/zpkt/data/kits" rather than as a failed render later.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from hands import config
from hands.live.transport import McpTransport

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    status: str   # ok | warn | fail
    detail: str


def _config_source(env: Mapping[str, str]) -> Check:
    file = Path(env.get("ZPKT_RIG_CONFIG") or config.CONFIG_FILE).expanduser()
    overrides = sorted(f"ZPKT_{k.upper()}" for k in config.DEFAULTS if env.get(f"ZPKT_{k.upper()}"))
    if file.exists():
        return Check("config", OK, f"{file}" + (f", overridden by {', '.join(overrides)}" if overrides else ""))
    if overrides:
        return Check("config", OK, f"no {file}; from {', '.join(overrides)}")
    return Check("config", WARN, f"no {file} and no ZPKT_* variables: using the defaults")


def _folder(name: str, path: Path) -> Check:
    return Check(name, OK, str(path)) if path.is_dir() else Check(name, FAIL, f"{path} does not exist")


def _kits(rig: config.Rig, kits_dir: Path, sets_dir: Path) -> list[Check]:
    metas = sorted(kits_dir.glob("*.json")) if kits_dir.is_dir() else []
    if not metas:
        return [Check("kits", FAIL, f"no kits in {kits_dir}")]
    out = []
    for meta in metas:
        try:
            set_name = json.loads(meta.read_text())["set"]
        except (ValueError, KeyError) as exc:
            out.append(Check(f"kit {meta.stem}", FAIL, f"{meta}: unreadable ({exc})"))
            continue
        if not (sets_dir / f"{set_name}.als").is_file():
            out.append(Check(f"kit {meta.stem}", FAIL, f"its set {set_name}.als is not in {sets_dir}"))
        elif not rig.is_ours(set_name):
            out.append(Check(f"kit {meta.stem}", FAIL,
                             f"{set_name} has none of the prefixes {list(rig.set_prefixes)}: the guards would stop"))
        else:
            out.append(Check(f"kit {meta.stem}", OK, set_name))
    return out


def _live(rig: config.Rig, client: McpTransport) -> list[Check]:
    from hands.live import session

    app = Path("/Applications") / f"{rig.live_app}.app"
    out = [Check("live app", OK, rig.live_app) if app.is_dir() else Check("live app", WARN, f"{app} not found")]
    if not session._answers(client):
        return out + [Check("live answers", FAIL, "no answer from Live's remote script")]
    out.append(Check("live answers", OK, "yes"))
    front = session._front()
    if front is None:
        out.append(Check("front set", WARN, "no Live window in front (launching or loading?)"))
    else:
        out.append(Check("front set", OK if rig.is_ours(front) else WARN,
                         front if rig.is_ours(front) else f"{front} is not ours: the guards would stop"))
    return out


def run(client: McpTransport | None = None, env: Mapping[str, str] = os.environ) -> list[Check]:
    """All checks, in order. `client` None skips the ones that talk to Live."""
    rig = config.rig()
    kits_dir = Path(env["HANDS_KITS"]).expanduser() if env.get("HANDS_KITS") else rig.data_dir / "kits"
    sets_dir = Path(env["HANDS_SETS"]).expanduser() if env.get("HANDS_SETS") else rig.sets_dir
    checks = [_config_source(env), _folder("sets_dir", sets_dir), _folder("data_dir", rig.data_dir)]
    checks += _kits(rig, kits_dir, sets_dir)
    if client is not None:
        checks += _live(rig, client)
    return checks
