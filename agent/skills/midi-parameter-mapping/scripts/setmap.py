#!/usr/bin/env python3
"""setmap.py - edit AgentMap's config.json (hot-reloaded by the running script).

Writes to the installed config by default:
  ~/Music/Ableton/User Library/Remote Scripts/AgentMap/config.json
Override with --config PATH or env AGENTMAP_CONFIG.

Examples:
  # map CC 74 (ch0) to a device parameter (track 5, device 0, parameter 8)
  setmap.py add --cc 74 --target device_param --track 5 --device 0 --parameter 8
  # map CC 82 to a track's volume
  setmap.py add --cc 82 --target track_volume --track 5
  # endless encoder in relative mode
  setmap.py add --cc 71 --mode relative_two_compliment --target track_pan --track 5
  setmap.py list
  setmap.py remove --cc 74            # remove mappings for CC 74 (ch0)
  setmap.py clear

Adding a mapping for a CC/channel that already exists replaces it.
"""
import argparse
import json
import os
import sys

DEFAULT_CONFIG = os.environ.get(
    "AGENTMAP_CONFIG",
    os.path.expanduser(
        "~/Music/Ableton/User Library/Remote Scripts/AgentMap/config.json"),
)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"mappings": []}


def save(path, data):
    # Atomic write so the hot-reloader never reads a partial file.
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add or replace a mapping")
    a.add_argument("--cc", type=int, required=True)
    a.add_argument("--channel", type=int, default=0)
    a.add_argument("--mode", default="absolute")
    a.add_argument("--avoid-takeover", action="store_true")
    a.add_argument("--target", default="device_param",
                   choices=["device_param", "track_volume", "track_pan",
                            "send", "master_volume"])
    a.add_argument("--track")            # int index or "master"
    a.add_argument("--device", type=int)
    a.add_argument("--parameter", type=int)
    a.add_argument("--send", type=int)

    r = sub.add_parser("remove", help="remove mappings for a CC/channel")
    r.add_argument("--cc", type=int, required=True)
    r.add_argument("--channel", type=int, default=0)

    sub.add_parser("list", help="print current mappings")
    sub.add_parser("clear", help="remove all mappings")

    args = ap.parse_args()
    data = load(args.config)
    maps = data.setdefault("mappings", [])

    if args.cmd == "list":
        print(json.dumps(data, indent=2))
        return

    if args.cmd == "clear":
        data["mappings"] = []
        save(args.config, data)
        print("cleared")
        return

    if args.cmd == "remove":
        before = len(maps)
        data["mappings"] = [m for m in maps
                            if not (int(m.get("cc")) == args.cc
                                    and int(m.get("channel", 0)) == args.channel)]
        save(args.config, data)
        print(f"removed {before - len(data['mappings'])} mapping(s)")
        return

    # add
    m = {"cc": args.cc, "channel": args.channel, "mode": args.mode,
         "target": args.target}
    if args.avoid_takeover:
        m["avoid_takeover"] = True
    track = args.track
    if track is not None and track != "master":
        track = int(track)
    if args.target == "device_param":
        if track is None or args.device is None or args.parameter is None:
            sys.exit("device_param needs --track --device --parameter")
        m.update(track=track, device=args.device, parameter=args.parameter)
    elif args.target in ("track_volume", "track_pan"):
        if track is None:
            sys.exit(f"{args.target} needs --track")
        m["track"] = track
    elif args.target == "send":
        if track is None or args.send is None:
            sys.exit("send needs --track --send")
        m.update(track=track, send=args.send)
    # master_volume needs nothing else

    data["mappings"] = [x for x in maps
                        if not (int(x.get("cc")) == args.cc
                                and int(x.get("channel", 0)) == args.channel)]
    data["mappings"].append(m)
    save(args.config, data)
    print("added:", json.dumps(m))


if __name__ == "__main__":
    main()
