"""Surfaces made on request: a page of MiniLab controls (and macros) from a sentence, kept with the project.

The page's "Make a surface" sends what Anthony typed. `make` reads what the set holds (every track's mixer and
devices, with what each parameter shows now and at its ends), asks Claude for one page as JSON, checks every control
against the set (what is not there is dropped and said so), and saves it as
<sets_dir>/surfaces/<set>/<name>.json. Every file there is a page of the desk after desk.json's own.

A surface is a desk.json page plus where it came from:

    {"name": "Low end", "what": "one line", "prompt": "what was asked", "made": "2026-11-24 10:02",
     "controls": {"k1": {"track": "kick", "device": "desk EQ", "param": "1 Gain A", "label": "Sub"},
                  "k2": {"label": "Hats dark", "macro": [{"track": "Hats bus", "device": "desk EQ",
                                                          "param": "7 Gain A", "from": "0 dB", "to": "-9 dB"}]},
                  "f1": {"track": "Kick bus", "param": "volume"}, "b1": {"track": "Hats bus", "param": "mute"}},
     "notes": ["what was left out and why"]}

Slots: k1-k8 knobs, f1-f4 faders, b1-b8 pads (switches: mute, solo, a device's on/off, any two-state parameter).
A macro moves several parameters at once, each from its "from" to its "to" (as Live shows them: "200 Hz", "-6 dB",
"35 %", or "min", "max", "current") as the control goes from 0 to 1.

Claude is called through the Claude Code CLI, headless, with no tools: it only writes the JSON. The CLI must be
signed in on this Mac (`claude`, then /login), or HARNESS_OAUTH / the harness's Keychain item must hold a token.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from hands import config

SLOTS = [f"k{i}" for i in range(1, 9)] + [f"f{i}" for i in range(1, 5)] + [f"b{i}" for i in range(1, 9)]
MODEL = os.environ.get("MIXDESK_MODEL", "sonnet")
TIMEOUT_S = 180
KEYCHAIN_ITEM = "zpkt-claude-oauth"      # the harness's Claude login, if it has one (contrib/harness config.py)


class SurfaceError(Exception):
    pass


def folder(set_name: str) -> Path:
    return config.rig().sets_dir / "surfaces" / set_name


def pages(set_name: str) -> list[dict]:
    """The saved surfaces as desk pages, oldest first."""
    d = folder(set_name)
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []:
        try:
            s = json.loads(p.read_text())
            out.append({"name": s["name"], "what": s.get("what", ""), "controls": s["controls"], "surface": p.name,
                        "prompt": s.get("prompt", "")})
        except (ValueError, KeyError):
            continue
    return out


def parse_inventory(text: str) -> dict:
    """{(track, device, param): {"now", "min", "max", "q"}} from the pager's tab-separated lines."""
    inv = {}
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) >= 7:
            inv[(f[0], f[1], f[2])] = {"now": f[3], "min": f[4], "max": f[5], "q": f[6] == "Q"}
    return inv


def _inventory_text(inv: dict) -> str:
    """The inventory for the prompt: grouped, one parameter a line."""
    out, last = [], None
    for (track, device, param), v in inv.items():
        head = (track, device)
        if head != last:
            out.append(f"\n## track {track!r}" + (f", device {device!r}" if device else ", mixer"))
            last = head
        out.append(f"- {param}: now {v['now']} (range {v['min']} .. {v['max']}){' [switch/list]' if v['q'] else ''}")
    return "\n".join(out)


def prompt_for(request: str, inv: dict, existing: list[str]) -> str:
    return f"""You are building one control-surface page for a MIDI controller (Arturia MiniLab 3) that drives an Ableton Live set.

The musician asked:
<request>
{request}
</request>

The page has these slots: knobs k1..k8 (continuous parameters or macros), faders f1..f4 (continuous: usually volumes or macros), pads b1..b8 (switches: mute, solo, a device's "Device On", any two-state parameter). Leave slots out rather than fill them with things that were not asked for or do not serve the request. Put related controls next to each other. Levels (track and bus volumes) go on faders first, knobs only when the faders are used up. If two controls on the page drive the same parameter, say so in "notes".

A control is one of:
- a mixer control: {{"track": T, "param": "volume" | "pan" | "mute" | "solo" | "send:<return name>", "label": "short"}}
- a device parameter: {{"track": T, "device": D, "param": P, "label": "short"}}
- a macro (one knob or fader moving several parameters together): {{"label": "short", "macro": [{{"track": T, "device": D, "param": P, "from": "<shown value>", "to": "<shown value>"}}, ...]}}. For a mixer parameter in a macro, leave "device" out. "from" is where each parameter sits with the control at 0 and "to" at full; write them the way the set shows values ("200 Hz", "-6 dB", "35 %"), inside that parameter's range, or "min" / "max" / "current" ("current" is fixed to the value shown now when the page is saved). Use macros when the request names a gesture across several things ("darken all the hats", "open the filter and push the drive").

Use ONLY tracks, devices and parameters from the inventory below, spelled exactly. Labels are at most 14 characters, plain words a musician reads at a glance.

Names already taken by other pages: {json.dumps(existing)}

Reply with ONE JSON object and nothing else (no code fence, no prose):
{{"name": "<page name, at most 18 characters>", "what": "<one plain sentence saying what the page is for>", "controls": {{"k1": {{...}}, "f1": {{...}}, "b1": {{...}}}}, "notes": ["<anything asked for that the set cannot do, one short sentence each>"]}}

# The set
{_inventory_text(inv)}
"""


def _token() -> str | None:
    tok = os.environ.get("HARNESS_OAUTH")
    if tok:
        return tok
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM, "-a", os.environ.get("USER", ""), "-w"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def ask_claude(prompt: str) -> str:
    """One answer from Claude through the Claude Code CLI: no tools, no project settings, a neutral folder."""
    cli = shutil.which("claude") or str(Path("~/.local/bin/claude").expanduser())
    if not Path(cli).exists():
        raise SurfaceError("the Claude Code CLI is not installed on this Mac")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    tok = _token()
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    work = Path("~/_agent_scratch/mixdesk/surface-jobs").expanduser()
    work.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([cli, "-p", "--output-format", "json", "--max-turns", "1", "--model", MODEL,
                            "--setting-sources", "", "--tools", ""],
                           input=prompt, capture_output=True, text=True, env=env, cwd=str(work), timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise SurfaceError(f"Claude did not answer in {TIMEOUT_S} s") from None
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise SurfaceError(f"the Claude CLI failed: {(r.stderr or r.stdout).strip()[:200]}") from None
    if d.get("is_error"):
        msg = str(d.get("result", ""))
        if "authenticate" in msg.lower() or "oauth" in msg.lower() or "login" in msg.lower():
            raise SurfaceError("Claude is signed out on this Mac. In a terminal run `claude`, then /login, and try again.")
        raise SurfaceError(f"Claude: {msg[:200]}")
    return str(d.get("result", ""))


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SurfaceError("Claude's answer had no JSON in it")
    try:
        return json.loads(m.group(0))
    except ValueError as exc:
        raise SurfaceError(f"Claude's JSON does not parse ({exc})") from None


_NUM = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+|inf))\s*([a-zA-Z%]*)")
_SCALE = {"khz": 1e3, "ms": 1e-3}


def shown_number(text: str) -> float | None:
    """A value as Live shows it, as a number in its base unit ("1.73 kHz" -> 1730); the pager reads them the same
    way (pager._num)."""
    m = _NUM.match(str(text))
    if not m:
        return None
    if "inf" in m.group(1):
        return -1e9 if m.group(1).startswith("-") else 1e9
    return float(m.group(1)) * _SCALE.get(m.group(2).lower(), 1.0)


def _end(want: str, v: dict, where: str, notes: list[str]) -> str | None:
    """One end of a macro's sweep, checked against the parameter: "current" becomes the value the set has now (so
    the sweep stays where it was made), a value outside the range becomes that end of the range, and one that
    cannot be read is None."""
    w = str(want).strip()
    if w.lower() == "current":
        return v["now"]
    if w.lower() in ("min", "max") or v["q"]:
        return w
    x, lo, hi = shown_number(w), shown_number(v["min"]), shown_number(v["max"])
    if x is None or lo is None or hi is None:
        notes.append(f"{where}: {w!r} is not a value this parameter shows ({v['min']} .. {v['max']}); left out.")
        return None
    lo, hi = min(lo, hi), max(lo, hi)
    if x < lo or x > hi:
        end = "min" if (x < lo) == (shown_number(v["min"]) <= shown_number(v["max"])) else "max"
        notes.append(f"{where}: {w} is outside {v['min']} .. {v['max']}; set to its {'lowest' if end == 'min' else 'highest'}.")
        return end
    return w


def _find(inv: dict, track: str, device: str, param: str) -> tuple | None:
    """The inventory key for a control, forgiving case and a return's letter."""
    want = (str(track).lower(), str(device or "").lower(), str(param).lower())
    for k in inv:
        if (k[0].lower(), k[1].lower(), k[2].lower()) == want:
            return k
    return None


def validate(surface: dict, inv: dict, taken: list[str]) -> dict:
    """The surface with only what the set holds, names spelled as the set spells them; `notes` says what went."""
    notes = [str(n) for n in surface.get("notes", []) if str(n).strip()]
    controls = {}

    def one(c: dict, where: str) -> dict | None:
        k = _find(inv, c.get("track", ""), c.get("device", ""), c.get("param", ""))
        if k is None:
            notes.append(f"{where}: {c.get('track')} / {c.get('device') or 'mixer'} / {c.get('param')} is not in the set; left out.")
            return None
        out = {"track": k[0], "param": k[2]}
        if k[1]:
            out["device"] = k[1]
        return out

    for slot, c in (surface.get("controls") or {}).items():
        if slot not in SLOTS or not isinstance(c, dict):
            notes.append(f"{slot}: not a slot of the MiniLab; left out.")
            continue
        label = str(c.get("label", "")).strip()[:18]
        if "macro" in c:
            subs = []
            for m in c.get("macro") or []:
                base = one(m, f"{slot} macro")
                if base is None:
                    continue
                if base["param"] in ("mute", "solo"):
                    notes.append(f"{slot} macro: {base['track']} {base['param']} is a switch, not part of a sweep; left out.")
                    continue
                v = inv[(base["track"], base.get("device", ""), base["param"])]
                where = f"{slot} macro, {base['track']} {base['param']}"
                a, b = _end(m.get("from", "min"), v, where, notes), _end(m.get("to", "max"), v, where, notes)
                if a is None or b is None:
                    continue
                subs.append({**base, "from": a, "to": b})
            if subs:
                controls[slot] = {"label": label or "Macro", "macro": subs}
            continue
        base = one(c, slot)
        if base is None:
            continue
        v = inv[(base["track"], base.get("device", ""), base["param"])]
        if slot.startswith("b") and not v["q"]:
            notes.append(f"{slot}: {base['param']} is not a switch, so it cannot sit on a pad; left out.")
            continue
        if label:
            base["label"] = label
        controls[slot] = base
    if not controls:
        raise SurfaceError("nothing in the answer matched the set: " + " ".join(notes)[:300])
    name = re.sub(r"[^A-Za-z0-9 ._+&-]", "", str(surface.get("name", "")))[:24].strip() or "Surface"
    base_name, n = name, 2
    while name.lower() in [t.lower() for t in taken]:
        name, n = f"{base_name} {n}", n + 1
    return {"name": name, "what": str(surface.get("what", "")).strip()[:200], "controls": controls, "notes": notes}


def save(surface: dict, set_name: str, prompt: str) -> Path:
    d = folder(set_name)
    d.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", surface["name"].lower()).strip("-") or "surface"
    path, n = d / f"{slug}.json", 2
    while path.exists():
        path, n = d / f"{slug}-{n}.json", n + 1
    path.write_text(json.dumps({**surface, "prompt": prompt, "made": time.strftime("%Y-%m-%d %H:%M"), "set": set_name}, indent=1))
    return path


def remove(set_name: str, file: str) -> Path:
    """Move a surface's file to the folder's "removed" folder (nothing is deleted)."""
    if "/" in file or not file.endswith(".json"):
        raise SurfaceError("bad surface file")
    src = folder(set_name) / file
    if not src.exists():
        raise SurfaceError(f"no surface {file}")
    gone = folder(set_name) / "removed"
    gone.mkdir(exist_ok=True)
    dst = gone / f"{time.strftime('%Y%m%d-%H%M%S')}-{file}"
    src.rename(dst)
    return dst


def make(request: str, inv: dict, set_name: str, taken: list[str], ask=ask_claude) -> tuple[Path, dict]:
    """The whole job: ask, check against the set, save. Returns the file and the surface."""
    surface = validate(extract_json(ask(prompt_for(request, inv, taken))), inv, taken)
    return save(surface, set_name, request), surface
