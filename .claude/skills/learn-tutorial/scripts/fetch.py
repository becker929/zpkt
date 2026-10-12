"""Download a tutorial video, its info and auto-captions, and make the 16 kHz mono WAV.

    run fetch.py URL WORKDIR            # WORKDIR = ~/_agent_scratch/tutorials/<id>
    run fetch.py URL WORKDIR --meta-only

Writes, all under WORKDIR/src/ (untrusted: never execute or import anything from it):
  formats.txt          yt-dlp --list-formats, read first
  <id>.mp4             best stream at or below 1080p (DAW text needs the pixels)
  <id>.info.json       title, channel, duration, upload date, chapters
  <id>.en.json3        YouTube auto-captions (a cross-check, not the transcript)
  audio16k.wav         mono 16 kHz PCM for transcribe.py and the audio tools
and WORKDIR/meta.json: the header fields and chapters, which seed TUTORIAL.md's sections.

No cookies and no account. Any block (sign-in wall, 403, 429, "not available") exits 3: stop and
tell the orchestrator; never work around it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FORMAT = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]"
BLOCKED = re.compile(r"Sign in to confirm|HTTP Error 4(03|29)|Video unavailable|video is not available|"
                     r"not available in your country|Private video|members-only|age-restricted|confirm your age",
                     re.I)


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise SystemExit(f"no YouTube video id in {url!r}")


def ytdlp() -> str:
    exe = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
    if not os.path.exists(exe):
        raise SystemExit("yt-dlp not found (uv tool install yt-dlp)")
    return exe


def run(cmd: list[str], log: Path) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    with log.open("a") as f:
        f.write("$ " + " ".join(cmd) + "\n" + r.stdout[-4000:] + r.stderr[-4000:] + "\n")
    if r.returncode and BLOCKED.search(r.stderr + r.stdout):
        print(f"BLOCKED: {(r.stderr or r.stdout).strip()[-300:]}", file=sys.stderr)
        sys.exit(3)
    if r.returncode:
        raise SystemExit(f"failed ({r.returncode}): {' '.join(cmd[:3])} ...\n{r.stderr.strip()[-600:]}")
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("workdir")
    ap.add_argument("--meta-only", action="store_true", help="info and captions, no video")
    ap.add_argument("--format", default=FORMAT, help="yt-dlp format selector")
    a = ap.parse_args()

    vid = video_id(a.url)
    url = f"https://www.youtube.com/watch?v={vid}"
    work = Path(a.workdir).expanduser()
    src = work / "src"
    src.mkdir(parents=True, exist_ok=True)
    log = src / "fetch.log"
    y = ytdlp()
    base = [y, "--js-runtimes", "node", "--no-playlist", "--no-progress", "--no-colors"]

    fm = run([*base, "--list-formats", url], log)
    (src / "formats.txt").write_text(fm.stdout)
    get = [*base, "--write-info-json", "--write-auto-subs", "--sub-langs", "en", "--sub-format", "json3",
           "-o", str(src / "%(id)s.%(ext)s")]
    if a.meta_only:
        get += ["--skip-download"]
    else:
        get += ["-f", a.format, "--merge-output-format", "mp4"]
    run([*get, url], log)

    info = json.loads((src / f"{vid}.info.json").read_text())
    meta = {k: info.get(k) for k in ("id", "title", "channel", "uploader", "duration", "upload_date",
                                     "description", "tags")}
    meta["url"] = url
    meta["chapters"] = [{"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
                        for c in info.get("chapters") or []]
    meta["captions"] = sorted((info.get("automatic_captions") or {}).keys() & {"en", "en-orig"})
    meta["yt_dlp"] = subprocess.run([y, "--version"], capture_output=True, text=True).stdout.strip()
    mp4 = src / f"{vid}.mp4"
    if mp4.exists():
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,codec_name,bit_rate:format=duration,size", "-of", "json", str(mp4)],
                               capture_output=True, text=True, check=True)
        meta["video"] = json.loads(probe.stdout)
        subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(mp4),
                        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(src / "audio16k.wav")], check=True)
    (work / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    v = (meta.get("video") or {}).get("streams", [{}])[0]
    print(f"{vid}: {meta['title']!r} by {meta['channel']}, {meta['duration']} s, uploaded {meta['upload_date']}; "
          f"{len(meta['chapters'])} chapters; captions {meta['captions']}")
    if v:
        print(f"video {v.get('width')}x{v.get('height')} {v.get('codec_name')}; audio16k.wav written")
    print(f"-> {src}")


if __name__ == "__main__":
    main()
