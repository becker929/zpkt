"""harness serve | job "<prompt>" | jobs | show <id> | timings [--turns N] | studio-music-mp3 [--dry-run] | lab-audio | lab-params
| lab-bars"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from . import jobs as J
from .config import Config


def main() -> None:
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="keep the socket to the site open and run jobs")
    j = sub.add_parser("job", help="run one job here, in the foreground")
    j.add_argument("prompt")
    sub.add_parser("jobs", help="list recent jobs")
    s = sub.add_parser("show", help="one job and its last events")
    s.add_argument("id")
    t = sub.add_parser("timings", help="studio's turn timings: first vs later turns, Safari vs Chrome, Bluetooth")
    t.add_argument("--turns", type=int, default=100)
    m = sub.add_parser("studio-music-mp3", help="studio's old FLAC music as MP3, which iPhone Safari can play")
    m.add_argument("--dry-run", action="store_true", help="only say what would be converted")
    la = sub.add_parser("lab-audio", help="HW002's stems and clips for the lab (/studio/lab/), outside the repo")
    la.add_argument("--set", help="the Live set whose clips and arrangement to read")
    la.add_argument("--out", help="where to write (default HARNESS_LAB_AUDIO)")
    lp = sub.add_parser("lab-params", help="HW002's 100 parameters for the lab, read from the set")
    lp.add_argument("--set", help="the Live set to read values from")
    lb = sub.add_parser("lab-bars", help="the arrange surface's bar library: what each bar of the lab's stems holds")
    lb.add_argument("--set", help="the Live set whose splash clip to read")
    ar = sub.add_parser("artist", help="the artist agent (docs/artist-agent.md): show its data, or propose works")
    ar.add_argument("action", choices=["show", "propose"])
    ar.add_argument("--dry-run", action="store_true", help="propose: print the new repertoire, don't keep it")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config()
    store = J.JobStore(cfg.jobs_dir)
    if a.cmd == "serve":
        from .service import serve
        asyncio.run(serve(cfg))
    elif a.cmd == "job":
        runner = J.Runner(cfg, store)
        job = runner.submit("job", a.prompt.splitlines()[0][:80], a.prompt)
        job = asyncio.run(runner.run_one(job))
        print(json.dumps(job.public(), indent=2))
    elif a.cmd == "jobs":
        for job in store.recent(20):
            print(f"{job.id}  {job.status:8}  {job.title}")
    elif a.cmd == "timings":
        from .studio.store import Store
        from .studio.timing import report
        print(report(Store(cfg.studio_dir).timings(a.turns)))
    elif a.cmd == "studio-music-mp3":
        from .studio.migrate import music_to_mp3
        from .studio.store import Store
        studio = Store(cfg.studio_dir)
        try:
            done = asyncio.run(music_to_mp3(studio, dry_run=a.dry_run))
        finally:
            studio.close()
        for c in done:
            print(f"#{c.seq}  {c.status:13}  {c.source}" + (f" -> {c.mp3}" if c.mp3 else "")
                  + (f"  ({c.error})" if c.error else ""))
        print(f"{sum(c.status == 'converted' for c in done)} converted of {len(done)} FLAC music messages")
    elif a.cmd == "artist":
        from .studio import artist as A
        art = A.Artist(cfg.studio_dir / "artist", A.SEED)
        try:
            if a.action == "show":
                print(A.show(art))
            else:
                out = asyncio.run(A.propose(art, cfg.studio_model, cfg.cli_path, J.job_env(cfg), dry_run=a.dry_run))
                print(out["notes"])
                print(json.dumps(out["works"], indent=2) if a.dry_run else f"kept as repertoire v{out['version']}")
        finally:
            art.close()
    elif a.cmd == "lab-audio":
        from pathlib import Path

        from .studio import lab_audio
        kw = {"als": Path(a.set).expanduser()} if a.set else {}
        print(lab_audio.summary(lab_audio.build(Path(a.out).expanduser() if a.out else cfg.lab_audio, **kw)))
    elif a.cmd == "lab-params":
        from pathlib import Path

        from .studio import lab_params
        rows = lab_params.build(Path(a.set).expanduser()) if a.set else lab_params.build()
        by = {}
        for r in rows:
            by.setdefault(r["stage"], []).append(r)
        for stage, rs in by.items():
            print(f"{stage}: {len(rs)}")
        print(f"{len(rows)} parameters -> {lab_params.OUT}")
    elif a.cmd == "lab-bars":
        from pathlib import Path

        from .studio import lab_bars
        kw = {"als": Path(a.set).expanduser()} if a.set else {}
        print(lab_bars.summary(lab_bars.build(**kw)))
        print(f"-> {lab_bars.OUT}")
    elif a.cmd == "show":
        job = store.load(a.id)
        print(json.dumps({"job": job.public() if job else None, "events": store.events(a.id)}, indent=2))


if __name__ == "__main__":
    main()
