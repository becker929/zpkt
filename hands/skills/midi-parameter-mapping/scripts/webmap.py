#!/usr/bin/env python3
"""webmap.py - bridge AgentMap's config.json to the MiniLab 3 web controller.

Serves the interactive MiniLab 3 web page and a live `labels.json` derived from
the current MIDI mappings. Whenever you change a mapping (via setmap.py or by
editing config.json), the page picks it up within ~1s and relabels the matching
physical control, so the on-screen surface always mirrors the real map.

How the match works: each mapping is keyed by the raw MIDI CC it listens to.
This translates that CC back to the physical MiniLab 3 control using the unit's
default CC map (both ARTURIA/User and DAW programs, which are disjoint), then
writes a human label for the mapping's Live target onto that control.

Usage:
    webmap.py --page ~/arturia-minilab3.html            # serve on :8731
    webmap.py --once                                    # print labels.json + exit
    webmap.py --resolve-names                            # friendly Live names via OSC

Then open  http://localhost:8731/  (optionally  ?style=flat  or  ?style=hc ).
The page auto-connects because it is served over http.

Endpoints:
    GET /            -> the web page (from --page)
    GET /labels.json -> {type, rev, labels:{encoders[8],faders[4],pads[8],main,shift}}
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_CONFIG = os.environ.get(
    "AGENTMAP_CONFIG",
    os.path.expanduser("~/Music/Ableton/User Library/Remote Scripts/AgentMap/config.json"),
)
DEFAULT_PAGE = os.environ.get("WEBMAP_PAGE", os.path.expanduser("~/arturia-minilab3.html"))
DEFAULT_ALC = os.path.expanduser("~/.agents/skills/ableton-live-control/scripts")

# MiniLab 3 default CC map, mirrored from the web controller (arturia-minilab3.html).
ARTURIA = {"main": 114, "encoders": [74, 71, 76, 77, 93, 18, 19, 16],
           "faders": [82, 83, 85, 17], "shift": 9}
DAW = {"main": 28, "encoders": [86, 87, 89, 90, 110, 111, 116, 117],
       "faders": [14, 15, 30, 31], "shift": 27}
PAD_CCS = list(range(102, 110))  # pads 1..8 (bank A default)


def build_reverse():
    """cc -> slot name ('encoder1'..'encoder8','fader1'..'fader4','pad1'..'pad8','main','shift')."""
    rev = {}
    for prog in (ARTURIA, DAW):
        for i, cc in enumerate(prog["encoders"]):
            rev[cc] = "encoder%d" % (i + 1)
        for i, cc in enumerate(prog["faders"]):
            rev[cc] = "fader%d" % (i + 1)
        rev[prog["main"]] = "main"
        rev[prog["shift"]] = "shift"
    for i, cc in enumerate(PAD_CCS):
        rev[cc] = "pad%d" % (i + 1)
    return rev


REVERSE = build_reverse()


def structural_label(m):
    """A compact, always-available label from the mapping's target fields."""
    t = m.get("target")
    tr = m.get("track")
    if t == "device_param":
        return "T%s D%s P%s" % (tr, m.get("device"), m.get("parameter"))
    if t == "track_volume":
        return "Trk%s Vol" % tr
    if t == "track_pan":
        return "Trk%s Pan" % tr
    if t == "send":
        return "Trk%s Snd%s" % (tr, m.get("send"))
    if t == "master_volume":
        return "Master Vol"
    return str(t or "?")


def make_resolver(alc_dir):
    """Best-effort friendly names via AbletonOSC. Returns a callable or None."""
    if not os.path.isdir(alc_dir):
        return None
    sys.path.insert(0, alc_dir)
    try:
        from live import Live  # noqa: E402
    except Exception:
        return None
    live = Live(timeout=1.5)
    pcache = {}          # (track, device) -> [param names]
    tcache = {"names": None}

    def track_names():
        if tcache["names"] is None:
            try:
                tcache["names"] = live.get("/live/song/get/track_names", timeout=1.5)
            except Exception:
                tcache["names"] = []
        return tcache["names"]

    def tname(track):
        if track == "master":
            return "Master"
        try:
            return str(track_names()[int(track)])
        except Exception:
            return "Trk%s" % track

    def resolve(m):
        t = m.get("target")
        try:
            if t == "device_param":
                key = (m.get("track"), m.get("device"))
                if key not in pcache:
                    tr, dev = key
                    try:
                        rep = live.get("/live/device/get/parameters/name",
                                       int(tr) if tr != "master" else "master",
                                       int(dev), timeout=1.5)
                        pcache[key] = list(rep[2:]) if len(rep) > 2 else []
                    except Exception:
                        pcache[key] = []
                p = m.get("parameter")
                names = pcache[key]
                if isinstance(p, int) and 0 <= p < len(names):
                    return str(names[p])
                return None
            if t == "track_volume":
                return "%s Vol" % tname(m.get("track"))
            if t == "track_pan":
                return "%s Pan" % tname(m.get("track"))
            if t == "send":
                return "%s Snd%s" % (tname(m.get("track")), m.get("send"))
            if t == "master_volume":
                return "Master Vol"
        except Exception:
            return None
        return None

    return resolve


def compute_labels(config_path, resolver=None):
    """Read config.json and return the labels payload the web page consumes."""
    labels = {"encoders": [""] * 8, "faders": [""] * 4, "pads": [""] * 8,
              "main": "", "shift": ""}
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        maps = cfg.get("mappings", [])
    except (OSError, ValueError):
        maps = []
    for m in maps:
        cc = m.get("cc")
        slot = REVERSE.get(cc)
        if not slot:
            continue
        text = None
        if resolver:
            try:
                text = resolver(m)
            except Exception:
                text = None
        if not text:
            text = structural_label(m)
        if slot.startswith("encoder"):
            labels["encoders"][int(slot[7:]) - 1] = text
        elif slot.startswith("fader"):
            labels["faders"][int(slot[5:]) - 1] = text
        elif slot.startswith("pad"):
            labels["pads"][int(slot[3:]) - 1] = text
        else:
            labels[slot] = text
    return labels


def config_rev(config_path):
    try:
        return os.stat(config_path).st_mtime_ns
    except OSError:
        return 0


def payload(config_path, resolver):
    return {"type": "minilab3", "rev": config_rev(config_path),
            "labels": compute_labels(config_path, resolver)}


def make_handler(config_path, page_path, resolver):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html", "/minilab", "/minilab.html"):
                try:
                    with open(page_path, "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                except OSError:
                    self._send(404, b"page not found: %s" % page_path.encode(), "text/plain")
                return
            if path == "/labels.json":
                body = json.dumps(payload(config_path, resolver)).encode()
                self._send(200, body, "application/json")
                return
            self._send(404, b"not found", "text/plain")

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--page", default=DEFAULT_PAGE)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("WEBMAP_PORT", "8731")))
    ap.add_argument("--resolve-names", action="store_true",
                    help="resolve friendly Live names via AbletonOSC (needs it running)")
    ap.add_argument("--alc", default=DEFAULT_ALC, help="ableton-live-control scripts dir")
    ap.add_argument("--once", action="store_true", help="print labels.json and exit")
    args = ap.parse_args()

    resolver = make_resolver(args.alc) if args.resolve_names else None
    if args.resolve_names and resolver is None:
        print("warning: name resolution unavailable; using structural labels",
              file=sys.stderr)

    if args.once:
        print(json.dumps(payload(args.config, resolver), indent=2))
        return

    handler = make_handler(args.config, args.page, resolver)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print("webmap serving http://%s:%d/  page=%s  config=%s%s"
          % (args.host, args.port, args.page, args.config,
             "  (resolving names)" if resolver else ""))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
