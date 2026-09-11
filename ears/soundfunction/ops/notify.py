#!/usr/bin/env python3
"""Post to the shared ntfy topic at one of three levels.

    python3 ops/notify.py fyi|ask|act "message" [--title T] [--link URL]

Reads NTFY_TOPIC from ops/local.env (never committed) or the environment.
Levels: fyi = low, silent. ask = default. act = high, mirrored into Apple
Reminders by the Mac subscriber.
"""
import argparse, os, sys, urllib.request
from pathlib import Path

LEVELS = {"fyi": "low", "ask": "default", "act": "high"}


def topic():
    env = Path(__file__).resolve().parent / "local.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("NTFY_TOPIC="):
                return line.split("=", 1)[1].strip().strip('"')
    t = os.environ.get("NTFY_TOPIC")
    if not t:
        sys.exit("no NTFY_TOPIC: put it in ops/local.env or the environment")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("level", choices=LEVELS)
    ap.add_argument("message")
    ap.add_argument("--title", default=None)
    ap.add_argument("--link", default=None)
    ap.add_argument("--from", dest="sender", default=os.environ.get("AGENT_NAME", "agent"))
    a = ap.parse_args()
    headers = {"Priority": LEVELS[a.level], "Title": a.title or f"[{a.level}] {a.sender}"}
    if a.link:
        headers["Click"] = a.link
    req = urllib.request.Request(f"https://ntfy.sh/{topic()}", data=a.message.encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print(r.status, r.read()[:120].decode(errors="replace"))


if __name__ == "__main__":
    main()
