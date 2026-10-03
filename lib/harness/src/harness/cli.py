"""harness serve | job "<prompt>" | jobs | show <id>"""

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
    elif a.cmd == "show":
        job = store.load(a.id)
        print(json.dumps({"job": job.public() if job else None, "events": store.events(a.id)}, indent=2))


if __name__ == "__main__":
    main()
