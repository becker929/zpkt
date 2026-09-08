#!/usr/bin/env python3
"""Mirror a shared ("anyone with the link") Google Drive folder into the local layout
the runner reads.   python3 lab/drive_fetch.py manifest.json dest/

manifest.json is a list of {id, title, mimeType, path} written from a Drive listing
(path = folder path relative to the shared root, e.g. "refs" or "stems/track-a").
Shortcuts are resolved by reading the shortcut's view page for the target id.
Large files that hit Drive's virus-scan page are fetched with the confirm token.
"""
import json, re, sys, urllib.request, urllib.parse
from pathlib import Path
UA = {"User-Agent": "Mozilla/5.0 (sound-function lab fetch)"}


def get(url, dest=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        ctype = r.headers.get("Content-Type", "")
        if dest is None or ctype.startswith("text/html"):
            return ctype, r.read()
        with open(dest, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b)
        return ctype, None


def resolve_shortcut(file_id):
    _, html = get(f"https://drive.google.com/file/d/{file_id}/view")
    ids = re.findall(rb"https://drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})", html)
    ids = [i.decode() for i in ids if i.decode() != file_id]
    return ids[0] if ids else None


def download(file_id, dest):
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    ctype, html = get(url, dest)
    if html is not None:   # got a page instead of the file: shortcut, virus-scan confirm, or an error
        m = re.search(rb'confirm=([0-9A-Za-z_-]+)', html) or re.search(rb'name="confirm" value="([^"]+)"', html)
        uuid = re.search(rb'name="uuid" value="([^"]+)"', html)
        if m:
            q = {"export": "download", "id": file_id, "confirm": m.group(1).decode()}
            if uuid: q["uuid"] = uuid.group(1).decode()
            ctype, html = get("https://drive.usercontent.google.com/download?" + urllib.parse.urlencode(q), dest)
        if html is not None:
            text = re.sub(rb"<[^>]+>", b" ", html)[:200]
            raise RuntimeError(f"no file for {file_id}: {text!r}")
    return ctype


def main(manifest, dest):
    dest = Path(dest); items = json.load(open(manifest)); ok = 0
    for it in items:
        if it["mimeType"] == "application/vnd.google-apps.folder": continue
        fid = it["id"]
        if it["mimeType"] == "application/vnd.google-apps.shortcut":
            target = resolve_shortcut(fid)
            if not target: print(f"skip {it['title']}: shortcut target not found", file=sys.stderr); continue
            fid = target
        out = dest / it.get("path", "") / it["title"]; out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size > 0: print(f"have {out}", file=sys.stderr); ok += 1; continue
        try:
            ctype = download(fid, out); print(f"got  {out} ({out.stat().st_size} bytes, {ctype})", file=sys.stderr); ok += 1
        except Exception as e:
            print(f"FAIL {it['title']}: {e}", file=sys.stderr)
    print(f"{ok} files in {dest}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
