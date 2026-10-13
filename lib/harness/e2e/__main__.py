"""`python -m e2e`: run the scenario against the real studio and write the report (see __init__.py)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import soundfile as sf

from . import checks, report, scenario, stack
from .phone import Phone


async def main(args: argparse.Namespace) -> int:
    from playwright.async_api import async_playwright

    parts = scenario.plan(args.only)
    folder = Path(args.out or Path("~/_agent_scratch/e2e/runs").expanduser() / time.strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "parts": parts, "browser": args.browser,
            "commit": report.commit(), "renders": "Live" if args.live else "cached Live renders, stand-ins for new ones"}
    print(f"run folder: {folder}\nparts: {', '.join(parts)}", flush=True)
    s = await stack.start(folder, live=args.live, real_screen=args.real_screen)
    print(f"studio on {s.base}; voice worker {s.studio.worker.info}", flush=True)
    expect = scenario.Expect()
    run = None
    try:
        async with async_playwright() as p:
            kind = p.webkit if args.browser == "webkit" else p.chromium
            browser = await kind.launch(args=["--autoplay-policy=no-user-gesture-required"]
                                        if args.browser == "chromium" else [])
            phone = Phone(browser, s.base, folder, s)
            try:
                await phone.open()
                await phone.start()
                ctx: dict = {}
                for part in parts:
                    print(f"== {part}", flush=True)
                    try:
                        await scenario.PARTS[part](phone, expect, ctx)
                    except Exception as exc:              # noqa: BLE001 - a part that breaks is a failed check
                        expect(f"Part '{part}' ran to the end", False, f"{type(exc).__name__}: {exc}")
                        await phone.shot(f"failed-{part}")
                        if not args.keep_going:
                            break
                await asyncio.sleep(1)
                page = await phone.collect()
            finally:
                await phone.close()
                await browser.close()
            run = checks.Run(page=page, engine=phone.recording.engine, ears=phone.recording.ears(),
                             events=phone.events, errors=phone.errors, db=folder / "studio" / "studio.sqlite3")
    finally:
        await s.close()
    results = expect.results + (checks.all_checks(run) if run else [])
    for r in results[len(expect.results):]:
        print(f"    {'PASS' if r.ok else 'FAIL'}  {r.name}: {r.detail[:160]}")
    if run:
        (folder / "wire.json").write_text(json.dumps(run.page["wire"]))
        (folder / "page.json").write_text(json.dumps({k: v for k, v in run.page.items() if k != "wire"}, indent=0))
        (folder / "engine.json").write_text(json.dumps(run.engine, indent=0))
        for ear in run.ears:
            if len(ear.samples):
                sf.write(folder / f"heard-{ear.id}.wav", ear.samples, ear.rate, subtype="PCM_16")
    path = report.write(folder, results, run, meta)
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed. Report: {path}")
    return 1 if failed else 0


def cli() -> None:
    ap = argparse.ArgumentParser(prog="python -m e2e", description="studio end to end, as Anthony uses it")
    ap.add_argument("--only", help=f"some parts, comma separated: {', '.join(scenario.PARTS)}")
    ap.add_argument("--browser", choices=["webkit", "chromium"], default="webkit")
    ap.add_argument("--live", action="store_true", help="render new plans in Live (supervised; default: stand-ins)")
    ap.add_argument("--real-screen", action="store_true", help="screenshots of the Mac's screen")
    ap.add_argument("--keep-going", action="store_true", help="run the next part after one fails")
    ap.add_argument("--out", help="the run's folder (default ~/_agent_scratch/e2e/runs/<time>)")
    sys.exit(asyncio.run(main(ap.parse_args())))


if __name__ == "__main__":
    cli()
