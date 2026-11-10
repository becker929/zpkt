"""booth: the service and Anthony's controls.

    booth serve                  the API on 127.0.0.1:<port> and the worker (one job at a time)
    booth open | close [REASON]  let jobs start, or stop starting them (open also requeues held jobs)
    booth status                 open or not and why, the queue, today's Live time
    booth check SCORE.json       what POST /v1/check answers; never touches Live
    booth plan SCORE.json        the compiled plan (tracks, note counts, mixer); never touches Live
    booth run SCORE.json         one job now, in this process, watched: needs a booth_ set in front of Live
    booth template [--finish]    once, watched: make booth_template from File > New Live Set
    booth survey [--palette V] [--only ID,ID] [--listen]
                                 watched: load palette instruments, write palettes/<v>.survey.json; --listen also
                                 renders a phrase each and records its loudness
    booth sample FILE            keep an audio file as a sample, as POST /v1/samples does; prints its id
    booth token --new            make the bot's token and keep it in the Keychain
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import secrets
import subprocess
import sys
from pathlib import Path

from . import HOME, PREFIX


def _runner(jobs, settings):
    from .live import Builder
    from .runner import Gate, Runner
    from hands.live.transport import LiveClient
    live = LiveClient()

    def notify(title: str, body: str) -> None:
        try:
            from harness.notify import notify as ntfy   # the harness's ntfy, when it is installed alongside
            ntfy(title, body)
        except ImportError:
            print(f"NOTIFY {title}: {body}", file=sys.stderr)

    return Runner(jobs, settings, Gate(settings), builder=lambda step: Builder(live, step=step), notify=notify)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="booth", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("open")
    c = sub.add_parser("close")
    c.add_argument("reason", nargs="*")
    sub.add_parser("status")
    for name in ("check", "plan", "run"):
        sub.add_parser(name).add_argument("score", type=Path)
    sub.add_parser("template").add_argument("--finish", action="store_true", help="finish booth_template, open in front, after a stop")
    sv = sub.add_parser("survey")
    sv.add_argument("--palette", help="a palette version (default: the one the guide serves)")
    sv.add_argument("--only", help="comma-separated instrument ids; the rest of the survey file is kept")
    sv.add_argument("--listen", action="store_true", help="play and render each one, and measure its loudness")
    sub.add_parser("sample").add_argument("file", type=Path)
    t = sub.add_parser("token")
    t.add_argument("--new", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from .config import KEYCHAIN_SERVICE, settings, token
    from .jobs import Jobs
    s = settings()
    HOME.mkdir(parents=True, exist_ok=True)

    if a.cmd in ("check", "plan"):
        from .check import check
        res = check(json.loads(a.score.read_text()))
        if a.cmd == "check" or not res.ok:
            print(json.dumps(res.json(), indent=2))
            return 0 if res.ok else 1
        from . import compile as C
        from . import palette as P
        plan = C.compile(res.score, P.load(res.score.palette))
        print(json.dumps({"bpm": plan.bpm, "beats": plan.beats, "render_beats": plan.render_beats, "returns": plan.returns,
                          "tracks": [{"name": t.name, "kind": t.kind, "plays": t.label, "notes": len(t.notes),
                                      **({"clips": t.sample.clips, "warp": t.sample.warp, "fit_beats": t.sample.fit_beats,
                                          "slices": t.sample.slices} if t.sample else {}),
                                      "volume_db": t.volume_db, "pan": t.pan, "room_db": t.room_db, "echo_db": t.echo_db,
                                      "settings": t.settings}
                                     for t in plan.tracks]}, indent=2))
        return 0

    if a.cmd == "sample":
        from . import samples as S
        try:
            meta, new = S.add(a.file.read_bytes())
        except S.SampleError as exc:
            print(f"{exc.code}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({**S.public(meta), "new": new}, indent=2))
        return 0

    if a.cmd == "token":
        if not a.new:
            print("set" if token() else "missing")
            return 0
        value = "zb1_" + secrets.token_hex(24)
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", getpass.getuser(), "-w", value],
                       check=True, capture_output=True)
        print(f"Saved a new token in the Keychain ({KEYCHAIN_SERVICE}). Give it to the bot with `node bot/secrets.mjs`;"
              " show it with `security find-generic-password -s zpkt-booth-token -w`.")
        return 0

    jobs = Jobs(HOME)
    if a.cmd == "open":
        n = _runner(jobs, s).open()
        print(f"open; {n} held job(s) back in the queue")
        return 0
    if a.cmd == "close":
        _runner(jobs, s).close(" ".join(a.reason) or "closed by Anthony")
        print("closed")
        return 0
    if a.cmd == "status":
        from . import palette as P
        r = _runner(jobs, s)
        print(json.dumps({"open": jobs.kv("open", "0") == "1", "would_start": r.gate.reason(jobs) or "yes",
                          "palette": s.palette or P.SERVED, "samples": s.samples,
                          "queue": [(j["id"], j["key"]) for j in jobs.queue()], "today": jobs.today()}, indent=2))
        return 0
    if a.cmd == "serve":
        from aiohttp import web
        from .server import app
        tok = token()
        if not tok:
            print("No booth token: run `booth token --new` first.", file=sys.stderr)
            return 2
        jobs.recover()
        web.run_app(app(jobs, _runner(jobs, s), s, tok), host="127.0.0.1", port=s.port)
        return 0
    if a.cmd == "run":
        from .check import check
        res = check(json.loads(a.score.read_text()))
        if not res.ok:
            print(json.dumps(res.json(), indent=2))
            return 1
        r = _runner(jobs, s)
        # a person is watching this one: open/closed, the hours and the quiet time are for the bot's jobs; only the
        # lease (a booth_ set in front of Live) still applies
        front = r.gate.front()
        why = None if front and front.startswith(PREFIX) else "Live is being used for something else"
        if why:
            print(f"not now: {why}", file=sys.stderr)
            return 1
        job, _ = jobs.add(f"cli:{a.score.name}:{secrets.token_hex(3)}", res.score.model_dump(), {})
        r.run(job)
        print(json.dumps(jobs.public(jobs.get(job["id"])), indent=2))
        return 0
    if a.cmd in ("template", "survey"):
        from . import palette as P
        from .live import finish_template, make_template, survey
        from hands.live.transport import LiveClient
        pal = P.load(a.palette) if a.cmd == "survey" and a.palette else P.served(s.palette)
        if a.cmd == "template" and a.finish:
            finish_template(LiveClient(), pal)
            print("finished booth_template")
        elif a.cmd == "template":
            print(make_template(LiveClient(), pal, Path("~/_agent_scratch/rummage/set").expanduser()))
        else:
            from datetime import datetime
            out = P.PALETTES / f"{pal.version}.survey.json"
            only = [i.strip() for i in a.only.split(",") if i.strip()] if a.only else None
            unknown = [i for i in only or [] if i not in pal.instruments]
            if unknown:
                print(f"not in palette {pal.version}: {unknown}", file=sys.stderr)
                return 2
            render = HOME / "survey" / f"{pal.version}-{datetime.now():%Y%m%d-%H%M%S}.wav"
            print(json.dumps(survey(LiveClient(), pal, out, only=only, listen=a.listen, render=render), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
