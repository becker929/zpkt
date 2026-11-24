"""harness serve | lab-audio | lab-params | lab-bars | artist show|propose | gemini [gemini-cli args]"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import Config, claude_env


def main() -> None:
    if sys.argv[1:2] == ["gemini"]:                   # everything after it is Gemini CLI's, flags included
        from .gemini import exec_cli
        exec_cli(sys.argv[2:])
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="the pages for the phone, on loopback behind the password")
    la = sub.add_parser("lab-audio", help="HW002's stems and clips for the lab (/studio/lab/), outside the repo")
    la.add_argument("--set", help="the Live set whose clips and arrangement to read")
    la.add_argument("--out", help="where to write (default HARNESS_LAB_AUDIO)")
    lp = sub.add_parser("lab-params", help="HW002's 100 parameters for the lab, read from the set")
    lp.add_argument("--set", help="the Live set to read values from")
    lb = sub.add_parser("lab-bars", help="the arrange surface's bar library: what each bar of the lab's stems holds")
    lb.add_argument("--set", help="the Live set whose splash clip to read")
    ar = sub.add_parser("artist", help="the artist agent (contrib/docs/design/artist-agent.md): show its data, or propose works")
    ar.add_argument("action", choices=["show", "propose"])
    ar.add_argument("--dry-run", action="store_true", help="propose: print the new repertoire, don't keep it")
    ge = sub.add_parser("gemini", help="Gemini CLI in this zpkt checkout, with the key from the Keychain (contrib/docs/gemini.md)")
    ge.add_argument("args", nargs=argparse.REMAINDER, help="passed to gemini as they are (-p, -m, --resume ...)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config()
    if a.cmd == "serve":
        from .service import serve
        asyncio.run(serve(cfg))
    elif a.cmd == "artist":
        from .studio import artist as A
        art = A.Artist(cfg.studio_dir / "artist", A.SEED)
        try:
            if a.action == "show":
                print(A.show(art))
            else:
                out = asyncio.run(A.propose(art, cfg.studio_model, cfg.cli_path, claude_env(cfg), dry_run=a.dry_run))
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


if __name__ == "__main__":
    main()
