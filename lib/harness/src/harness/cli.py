"""harness serve | job "<prompt>" | jobs | show <id> | timings [--turns N] | studio-music-mp3 [--dry-run] | lab-audio | lab-params
| lab-bars | artist show|propose | images gen|batch|list"""

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
    im = sub.add_parser("images", help="make images with Gemini, each one kept with its record (docs/images.md)")
    im.add_argument("action", choices=["gen", "batch", "list"])
    im.add_argument("what", nargs="?", help="gen: the prompt; batch: a JSON file of jobs")
    im.add_argument("--context", help="why these were made, in a sentence (shown with every image)")
    im.add_argument("--batch", help="the batch's name, e.g. wasteland-styles-1")
    im.add_argument("--title", default="")
    im.add_argument("--model", default=None)
    im.add_argument("--aspect", default="1:1")
    im.add_argument("--size", default=None, help="1K, 2K or 4K")
    im.add_argument("--input", action="append", default=[], help="a reference image to send with the prompt")
    im.add_argument("--parallel", type=int, default=4)
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
    elif a.cmd == "images":
        _images(cfg, a, ap)
    elif a.cmd == "show":
        job = store.load(a.id)
        print(json.dumps({"job": job.public() if job else None, "events": store.events(a.id)}, indent=2))


def _images(cfg: Config, a: argparse.Namespace, ap: argparse.ArgumentParser) -> None:
    from pathlib import Path

    from . import images as I
    from .config import secret
    store = I.Store(cfg.images_dir)
    if a.action == "list":
        recs, total, batches = store.page(0, 10_000, a.batch)
        for b in batches:
            print(f"{b['batch']}: {b['count']}")
        for r in recs[:40]:
            print(f"  {r.id}  {r.batch:24}  {r.model:24}  {r.title or r.prompt[:50]}")
        print(f"{total} images in {cfg.images_dir}")
        return
    if not a.what or not a.context or not a.batch:
        ap.error("images gen|batch need the prompt (or jobs file), --context and --batch")
    key = secret("gemini")
    if not key:
        ap.error("no Gemini key: security add-generic-password -U -s zpkt-gemini-api-key -a \"$USER\" -w")
    model = a.model or I.DEFAULT_MODEL
    if a.action == "gen":
        recs = I.generate(store, a.what, key=key, context=a.context, batch=a.batch, title=a.title, model=model,
                          aspect=a.aspect, size=a.size, inputs=[Path(p).expanduser() for p in a.input])
        errors = [] if recs else ["no image (see errors.jsonl)"]
    else:
        jobs = json.loads(Path(a.what).expanduser().read_text())
        recs, errors = I.run_batch(store, jobs, key=key, context=a.context, batch=a.batch, model=model, parallel=a.parallel)
    for r in recs:
        print(f"{r.id}  {r.seconds:5.1f}s  {r.width}x{r.height}  {r.title or r.prompt[:60]}")
    for e in errors:
        print(f"error: {e}")
    print(f"{len(recs)} kept in {cfg.images_dir}; see {cfg.app_url}/studio/images/?batch={a.batch}")


if __name__ == "__main__":
    main()
