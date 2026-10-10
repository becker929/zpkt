"""Spoken intros for /skrng batches: what a batch tests, said once before its first track.

  python3 lib/record/batch_intro.py SITE 7.5                  # words from the batch title
  python3 lib/record/batch_intro.py SITE 8 "Kick distortion. ..."
  python3 lib/record/batch_intro.py SITE all                  # every batch without an intro

SITE is a checkout of the site repo (e.g. ~/_agent_scratch/site). Makes the MP3 with
`say` (Daniel, as the track announcements), uploads it to R2 at
audio/skrng/tts/batch-<n>-<hash>.mp3 and sets "announce" and "say" on the batch in
skrng/batches.json ("say" without the batch id: the voice review says that
itself). New words give a new URL, so a cached old intro never plays.
Publishing is public: only run it for batches Anthony has approved. Commit and PR the
batches.json change in the site repo as usual.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

BUCKET = "anthonybecker-audio"


def spoken_id(n) -> str:
    """7.5 -> "Batch 7, part 5"; 5 -> "Batch 5"."""
    whole, _, part = str(n).partition(".")
    return f"Batch {whole}, part {part}" if part else f"Batch {whole}"


def from_title(n, title: str) -> str:
    """'Batch 7.5 — Colour: 6 versions ... (6 Oct)' -> 'Batch 7, part 5. Colour: 6 versions ....'"""
    t = re.sub(r"^Batch [\d.]+\s*[—–-]\s*", "", title)
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t).strip()
    t = re.sub(r"(\d)\s?s\b", r"\1 seconds", t)   # "40 s": say reads the letter
    t = t[:1].upper() + t[1:]
    return f"{spoken_id(n)}. {t}{'' if t.endswith('.') else '.'}"


def tts(text: str, mp3: pathlib.Path) -> None:
    """500 ms of silence, the words (trimmed, at -16 LUFS), 500 ms of silence."""
    with tempfile.TemporaryDirectory() as d:
        aiff = pathlib.Path(d) / "say.aiff"
        subprocess.run(["say", "-v", "Daniel", "-o", str(aiff), text], check=True)
        pad = ["-f", "lavfi", "-t", "0.5", "-i", "anullsrc=r=44100:cl=stereo"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *pad, "-i", str(aiff), *pad, "-filter_complex",
                        "[1:a]aresample=44100,aformat=channel_layouts=stereo,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "loudnorm=I=-16:TP=-1.5,aresample=44100[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]",
                        "-map", "[a]", "-b:a", "128k", str(mp3)], check=True)


def publish(site: pathlib.Path, batches: list, n, text: str) -> str:
    entry = next(b for b in batches if b["n"] == n)
    key = f"audio/skrng/tts/batch-{str(n).replace('.', '-')}-{hashlib.md5(text.encode()).hexdigest()[:6]}.mp3"
    if entry.get("announce") == "/" + key:
        return key
    with tempfile.TemporaryDirectory() as d:
        mp3 = pathlib.Path(d) / "intro.mp3"
        tts(text, mp3)
        subprocess.run(["npx", "-y", "wrangler@4.145.0", "r2", "object", "put", f"{BUCKET}/{key}", "--file", str(mp3),
                        "--content-type", "audio/mpeg", "--remote"], check=True, capture_output=True, cwd=site)
    # The voice review says "Batch N. K tracks." itself, then "say": keep the batch id out of it.
    entry["announce"], entry["say"] = "/" + key, re.sub(r"^Batch \d+(, part \d+)?\.\s*", "", text)
    return key


def main() -> None:
    site, which = pathlib.Path(sys.argv[1]).expanduser(), sys.argv[2]
    path = site / "skrng/batches.json"
    batches = json.loads(path.read_text())
    if which == "all":
        todo = [(b["n"], from_title(b["n"], b["title"])) for b in batches if not b.get("announce")]
    else:
        n = next(b["n"] for b in batches if str(b["n"]) == which)
        title = next(b["title"] for b in batches if b["n"] == n)
        todo = [(n, sys.argv[3] if len(sys.argv) > 3 else from_title(n, title))]
    for n, text in todo:
        print(f"{n}: {publish(site, batches, n, text)}  {text}", flush=True)
        path.write_text(json.dumps(batches, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
