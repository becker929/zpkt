"""Render a page frame by frame in headless Chrome and mux it with its soundtrack.

  uv run python tools/render.py                    # the demo -> out/zpkt-hw002-demo.mp4
  uv run python tools/render.py --stills 3 14 20   # stills + out/stills/sheet.jpg
  uv run python tools/render.py --from 18 --to 24  # a range, for checking motion
  uv run python tools/render.py --page reel.html --name zpkt-hw002-long.mp4   # the 102-second cut

The soundtrack is whatever the page's <audio id="a"> plays.
"""
import argparse
import base64
import pathlib
import subprocess
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
FPS = 30


def open_page(p, page_name: str):
    browser = p.chromium.launch(channel="chrome", headless=True,
                                args=["--allow-file-access-from-files", "--force-color-profile=srgb"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto((ROOT / page_name).as_uri() + "?render")
    page.evaluate("window.READY")
    if errors:
        raise SystemExit("page errors:\n" + "\n".join(errors))
    return browser, page, errors


def grab(page, t: float, fmt: str = "jpeg") -> bytes:
    mime = "image/png" if fmt == "png" else "image/jpeg"
    url = page.evaluate(f"(async () => {{ await prepare({t}); renderAt({t}); "
                        f"return document.getElementById('c').toDataURL('{mime}', 0.94); }})()")
    return base64.b64decode(url.split(",", 1)[1])


def stills(times: list[float], page_name: str) -> None:
    d = OUT / "stills"
    d.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, page, errors = open_page(p, page_name)
        paths = []
        for t in times:
            path = d / f"t{t:07.3f}.jpg"
            path.write_bytes(grab(page, t))
            paths.append(path)
        browser.close()
    if errors:
        print("errors:", *errors, sep="\n  ")
    cols = 3
    inputs = sum((["-i", str(p)] for p in paths), [])
    n = len(paths)
    rows = -(-n // cols)
    pad = cols * rows - n
    filt = "".join(f"[{i}:v]scale=640:360[v{i}];" for i in range(n))
    if pad:
        filt += "".join(f"color=black:s=640x360:d=1[p{j}];" for j in range(pad))
    labels = "".join(f"[v{i}]" for i in range(n)) + "".join(f"[p{j}]" for j in range(pad))
    layout = "|".join(f"{(i % cols) * 640}_{(i // cols) * 360}" for i in range(cols * rows))
    filt += f"{labels}xstack=inputs={cols * rows}:layout={layout}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", filt, "-frames:v", "1",
                    "-q:v", "3", str(d / "sheet.jpg")], check=True)
    print(d / "sheet.jpg")


def video(t0: float, t1: float | None, name: str, page_name: str) -> None:
    with sync_playwright() as p:
        browser, page, errors = open_page(p, page_name)
        duration = page.evaluate("window.ANALYSIS.duration")
        sound = ROOT / page.evaluate("document.getElementById('a').getAttribute('src')")
        t1 = duration if t1 is None else min(t1, duration)
        frames = int(round((t1 - t0) * FPS))
        out = OUT / name
        ff = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y",
             "-framerate", str(FPS), "-f", "image2pipe", "-c:v", "mjpeg", "-i", "-",
             "-ss", f"{t0}", "-t", f"{frames / FPS}", "-i", str(sound),
             "-map", "0:v", "-map", "1:a",
             "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
             "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", "-shortest", str(out)],
            stdin=subprocess.PIPE,
        )
        start = time.time()
        for f in range(frames):
            ff.stdin.write(grab(page, t0 + f / FPS))
            if f % 150 == 0:
                print(f"frame {f}/{frames}  {time.time() - start:.0f}s", flush=True)
        ff.stdin.close()
        ff.wait()
        browser.close()
    if errors:
        print("errors:", *errors, sep="\n  ")
    print(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", nargs="*", type=float)
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--name", default="zpkt-hw002-demo.mp4")
    ap.add_argument("--page", default="demo.html")
    a = ap.parse_args()
    if a.stills:
        stills(a.stills, a.page)
    else:
        video(a.t0, a.t1, a.name, a.page)


if __name__ == "__main__":
    main()
