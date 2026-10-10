# demo

A 33-second demo for ZPKT + HW002. The soundtrack is HW002 itself. Every
effect is built from a screen recording of Ableton Live playing HW002, and
Live always shows the bar you hear. Each frame depends only on its time and
on the measured soundtrack, so the same time always gives the same frame.

```bash
uv run python tools/edit.py      # cut the soundtrack, measure it → out/demo/soundtrack.wav, analysis.js
uv run python tools/footage.py   # align the Live recording to the edit → out/demo/frames/live/
uv run python tools/render.py    # headless Chrome + WebGL → out/zpkt-hw002-demo.mp4
uv run python tools/render.py --stills 3 8 20   # check frames → out/stills/sheet.jpg
uv run python tools/words.py     # words on screen per minute
open demo.html                   # live preview with sound: click to play, ← → move one bar
```

Published at [anthonybecker.me/demos/7/zpkt-hw002](https://anthonybecker.me/demos/7/zpkt-hw002/).
The video, its master and the poster are in R2 (`anthonybecker-audio`, keys
`audio/demos/zpkt-hw002-demo.mp4`, `zpkt-hw002-demo-master.mp4`, `zpkt-hw002-poster.jpg`),
served at `/audio/demos/`. The web copy is the master re-encoded at CRF 19:

```bash
ffmpeg -i out/zpkt-hw002-demo.mp4 -c:v libx264 -preset slow -crf 19 -maxrate 14M -bufsize 28M \
  -pix_fmt yuv420p -c:a aac -b:a 256k -movflags +faststart out/zpkt-hw002-demo-web.mp4
```

## The edit

Source: `~/_agent_scratch/renders/hw002_121_full_aligned.wav` (160 BPM, bar 1 at 0 s).
Every cut falls on a bar line. Peaks are limited to −1 dBTP; the audio is not otherwise mastered.

| Time | HW002 bars | Effect | On screen |
|---|---|---|---|
| 0:00 | 93–96 | Textmode: Live as coloured text, sharper every bar | zpkt presents |
| 0:06 | 97–98 | Tunnel lined with Live's arrangement | HW002 |
| 0:09 | 99–100 | Live, plain | no generated audio / 100% ableton live |
| 0:12 | 101–104 | Rotozoomer of Live screens, sine scroller | made by becker929 and four ai agents … |
| 0:18 | 121–124 | A box with each member's screen on one side, over a floor of Live | ears, hands, taste, engineer |
| 0:24 | 125–128 | Kaleidoscope of Live with a plasma, unfolding back to Live | ZPKT |
| 0:30 | 177–178 | The whole song as text, then the screen switches off | HW002 · zpkt · becker929 · 2026 |

The box's sides: ears is the arrangement playing; hands is the insert where it
turns the kick sampler's Transp and Volume; taste is the arrangement before and
after an 8-bar cut, side by side; engineer is the insert where it runs Edit >
Delete Time on bars 105–112.

`tools/words.py` counts 53 words on screen in 33 s (96 a minute). The 102-second
cut has 318 a minute.

## The footage

`out/footage/main.mp4` is Live playing a copy of `HW002_121_full.als` from bar 1
to 182, recorded on 6 October 2026. `knob.mp4` and `cut.mp4` are the hands and
engineer inserts. Filming needs Live; nothing else here does.

```bash
cd hands && uv run python ../demo/tools/livectl.py open   # copy the set into the HW002 project, save the open set, open the copy
cd hands && uv run python ../demo/tools/film.py main      # record bars 1-182 playing, with a song-time log
cd hands && uv run python ../demo/tools/film.py knob      # hands sets the kick sampler's Transp and Volume
cd hands && uv run python ../demo/tools/film.py cut       # engineer runs Edit > Delete Time on bars 105-112, then undoes it
cd hands && uv run python ../demo/tools/livectl.py restore  # reopen the previous set, Don't Save the copy
```

- Sync: `main.sync.json` fits Live's song time against the footage clock (160.00 BPM, ~15 ms median error).
  Live's position display trails that by 0.385 s, measured where it flips to 97.1.1 and checked at bar 121. `footage.py` adds the lag.
- The copy drops the muted "Lethal Storm" reference track, so no commercial track appears on screen.
- Recording needs Screen Recording permission for the app that runs it, and it takes over the screen Live is on.

## The 102-second cut

`reel.html` is the earlier, longer cut, built from the same footage:

```bash
uv run python tools/edit.py long && uv run python tools/footage.py long && uv run python tools/assets.py
uv run python tools/render.py --page reel.html --name zpkt-hw002-long.mp4
```

Fonts are macOS system fonts: Silom and Monaco for the pixel text, Helvetica Neue Condensed Black for the logos.
`out/` holds the audio, the footage and the video, and stays out of git.
