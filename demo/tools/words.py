"""Count the words a page puts on screen, per minute.

  uv run python tools/words.py                  # demo.html
  uv run python tools/words.py reel.html        # the 102-second cut

Samples the page at 10 frames a second and logs every string drawn on the main
canvas at 25% opacity or more. A string counts once per appearance: a run of
samples where it stays on screen. Digits are folded together, so a counter
ticking over is one appearance, and a string shown for under 0.3 s (a
scramble's random letters) is ignored. For text wider than the screen (a
ticker or a scroller) only the words that were actually visible count.
"""
import re
import sys

from playwright.sync_api import sync_playwright
from render import ROOT

HOOK = """
(() => {
  const P = CanvasRenderingContext2D.prototype, orig = P.fillText;
  const alphaOf = s => { const m = /rgba\\([^)]*,\\s*([\\d.]+)\\)/.exec(s); return m ? Number(m[1]) : 1; };
  P.fillText = function (str, x, y, ...rest) {
    if (window.__rec && this.canvas.id === 'c') {
      const w = this.measureText(str).width, al = this.textAlign;
      const x0 = al === 'center' ? x - w / 2 : (al === 'right' || al === 'end') ? x - w : x;
      window.__rec.push({ s: String(str), a: this.globalAlpha * alphaOf(String(this.fillStyle)), x0, w });
    }
    return orig.call(this, str, x, y, ...rest);
  };
})();
"""
STEP = 3  # frames: 10 samples a second at 30 fps
MIN_RUN = 3  # samples: 0.3 s


def words_of(s: str) -> list[str]:
    return [w for w in s.split() if re.search(r"[A-Za-z0-9]", w)]


def main() -> None:
    page_name = sys.argv[1] if len(sys.argv) > 1 else "demo.html"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(HOOK)
        page.goto((ROOT / page_name).as_uri() + "?render")
        page.evaluate("window.READY")
        fps, dur = page.evaluate("[window.ANALYSIS.fps, window.ANALYSIS.duration]")
        samples = []
        for f in range(0, int(dur * fps), STEP):
            t = f / fps
            samples.append(page.evaluate(
                f"(async () => {{ await prepare({t}); window.__rec = []; renderAt({t}); "
                f"const r = window.__rec; window.__rec = null; return r; }})()"))
        browser.close()

    # runs of each (digit-folded) string: first sample, last sample, visible char span
    open_runs: dict[str, dict] = {}
    done: list[dict] = []
    for i, recs in enumerate(samples):
        seen = {}
        for r in recs:
            if r["a"] < .25 or not r["s"].strip():
                continue
            key = re.sub(r"\d", "#", r["s"])
            n = len(r["s"])
            cw = r["w"] / max(n, 1)
            lo = max(0, int(-r["x0"] / cw)) if cw else 0
            hi = min(n, int((1920 - r["x0"]) / cw) + 1) if cw else n
            if hi > lo:
                prev = seen.get(key)
                seen[key] = (r["s"], min(lo, prev[1]) if prev else lo, max(hi, prev[2]) if prev else hi)
        for key in list(open_runs):
            if key not in seen and i - open_runs[key]["last"] > 1:
                done.append(open_runs.pop(key))
        for key, (s, lo, hi) in seen.items():
            run = open_runs.setdefault(key, {"s": s, "first": i, "last": i, "lo": lo, "hi": hi})
            run["last"], run["lo"], run["hi"] = i, min(run["lo"], lo), max(run["hi"], hi)
    done += open_runs.values()

    total = 0
    shown = []
    for run in sorted(done, key=lambda r: r["first"]):
        if run["last"] - run["first"] + 1 < MIN_RUN:
            continue
        n = len(words_of(run["s"][run["lo"]:run["hi"]]))
        if n:
            total += n
            shown.append((run["first"] * STEP / fps, n, run["s"][run["lo"]:run["hi"]][:70]))
    for t, n, s in shown:
        print(f"{t:6.1f}s  {n:3d}  {s}")
    print(f"\n{page_name}: {total} words in {dur:.1f} s = {total / dur * 60:.0f} words per minute")


if __name__ == "__main__":
    main()
