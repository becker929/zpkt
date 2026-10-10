# studio: handoff (2026-10-10)

Where the voice production app stands after Phase 2 steps V1-V4 (`docs/plan-2026-10.md`). Read with
`docs/studio.md` (design and protocol) and `docs/voice-benchmark.md` (the speech models and how turns are timed).

Branch `p2-studio-web`, stacked on `stack-base-2026-10` (open PRs #26, #28-#30). It contains `p2-studio` (server,
agent, screenshots, voice worker), merged in.

## Done

| Step | What | Where |
|---|---|---|
| V4, the page | Phone page (plain ES modules): chat window with paging, bubbles, audio queue, mic worklet, turn controller. Scroll anchoring fixed (the reader's place is kept by row inside a run of steps). WebKit tests at an iPhone's size. | `lib/harness/src/harness/studio/static/`, `lib/harness/tests/ui/` |
| V1, speech | Parakeet TDT 0.6B v3 (MLX) + Silero VAD for speech-to-text and "tomato"; Kokoro (ONNX) for speech. Chosen and tuned by benchmark: 139/144 stop words, 0/96 false ends, 257 ms median after "tomato", 4.6% WER. Turn timings tagged by turn number, browser and audio route; `harness timings` reports them. Claude takes no audio input (text only). | `lib/voice/src/voice/{stt,tts,worker}.py`, `lib/voice/bench/stt_turns.py`, `studio/timing.py` |
| V3, music | `hands plan`: plans (kit + knob values), packed renders (one Live load + export per P plans), write-ahead ("more", "the other end"), render cache with nearest neighbour, A/B every bar at matched loudness. Skills `render-plan`, `ab-1bar`, `plan-cache`. | `hands/src/hands/plans/`, `.claude/skills/` |
| V2 + integration | Real stack test: page in Chromium, real server, real Kokoro/Parakeet, `hands plan ab`, A/B lights A and B, mic reopens. One typed turn with the real Claude session (about $0.08). | `lib/harness/tests/ui/test_stack.py` |

First supervised Live render (2026-10-10): kit `c8x4`, rumble Decapitator Drive 0.3/0.4/0.5/0.6 in one pass,
37 s (load 12.5 s, export 19.2 s), guards passed before and after; loudness rises ~0.7 LU per 0.1 drive; the
follow-up "more" A/B came from the cache in 0.65 s. Files in `~/_agent_scratch/plans/`.

## Not done yet

1. **A session on the phone.** Safari on the iPhone, Bluetooth in the car, over the tailnet. Then
   `uv run --project lib/harness harness timings` gives the first-vs-later, Safari-vs-Chrome and
   phone-vs-Bluetooth medians V1 asks for.
2. **Restart `harness serve`** (tmux) on this branch, or after merging; the running one serves older code.
3. Kits exist only for HW002 sections (`~/_agent_scratch/probepack/kits/`: c8x4, c8x16, d8x32, k8x16). A new
   section needs one built in the GUI (`probe_kit.py template ...`).

## Known limits and choices to revisit

- Speech starts ~0.5 s after Claude's first sentence (ONNX on CPU). `VOICE_TTS_MODEL=int8` halves it; the
  FluidAudio (Swift, ANE) worker from the bench would be ~0.1 s.
- Stop-word misses are robotic voices in babble noise; babble raises latency to ~850 ms.
- A Live render saves the set in front before switching (probe_kit). Its guard refuses unless an
  `HW002_121_pp*` / `HW002_121_v_*` set is in front, no dialog is open and Live answers. On 2026-10-10 the set in
  front (`HW002_121_pp_x_k8x16_s8_b8_7_break_colour_solo`) had unsaved changes and was saved; its previous file is
  in `~/_agent_scratch/plans/first/backup-break_colour_solo.als`.
- The process running renders needs macOS Accessibility (the guards and the Export dialog use System Events).
  tmux has it; Zed was granted it on 2026-10-10.
- The A/B uses BS.1770 integrated loudness via pyloudnorm, not mlab's meter (same standard).

## Running and testing

```bash
uv run --project lib/harness --extra dev pytest                     # 157 passed (UI tests need Playwright browsers)
uv run --project lib/voice --extra dev pytest                       # add VOICE_ENGINES=1 --extra engines: real models
uv run --project hands --extra plans --extra dev pytest             # 87 passed
STUDIO_STACK=1 uv run --project lib/harness --extra dev pytest lib/harness/tests/ui/test_stack.py   # real speech models
STUDIO_CLAUDE=1 ...same... -k real_claude                           # one real Claude turn
cd hands && uv run --extra plans hands plan ab A.json B.json        # a real render (Live, guarded)
```

The page's browser tests (`lib/harness/tests/ui`, marked `ui`) inject and capture audio:

- Injection: the mic is a WAV, through Chromium's fake capture device or a getUserMedia shim (a 1 kHz tone for the
  fake server; a Kokoro-spoken sentence ending in "tomato" for the real stack).
- Capture: every page's AudioContext destination is replaced by a tap into an AudioWorklet that records what the
  page plays, sample by sample, with audio-clock timestamps, and passes on silence (`tests/ui/heard.py`;
  `await heard(page)` returns the recordings). The tests check what came out, not what the page says:
  - `test_heard.py` (fake server): the reply's tone is heard, then the A/B, each pass lining up with the file to the
    sample (correlation 1.000, repeat boundaries exactly one file length apart, start within a sample of the
    scheduled time); "loop that three times" is exactly three passes then silence; after `stop_audio` the sound
    ends within the render quantum the page stopped it in; a context made after the page was away is recorded too;
    no sound reaches the speakers while the mic is open. That last one holds because the route settle (100 ms in
    that test) outlasts the output latency (~35 ms in headless Chromium): the mic opened ~95-105 ms after the last
    sound was heard. With the tests' usual 30 ms it was 5-25 ms, and a desktop browser without
    `navigator.audioSession` waits 0 ms, so there the mic can open while the last ~35 ms is still in the output.
  - `test_webkit.py`: the same capture in WebKit at iPhone size (a render played twice, to the sample).
  - `test_stack.py -k voice_loop` (STUDIO_STACK=1): a full voice loop. Kokoro's sentence goes in through the mic,
    Parakeet hears it and "tomato" ends the turn; the scripted reply is spoken by Kokoro and played by the page; the
    recording is resampled to 16 kHz and transcribed by the same Parakeet worker; word error rate under 15%
    (0% when written).

Browser tests cannot reproduce the iOS audio session: app switching, interruptions (calls, Siri), Bluetooth route
changes and the lock screen are simulated at best (a faked `visibilitychange`), and a desktop browser's output
latency is not a phone's. Those still need the phone.

Setup: `uv run --project lib/harness --extra dev playwright install chromium webkit`; the speech models download
on first use (Kokoro and Silero to `~/.cache/zpkt-voice`, Parakeet to the Hugging Face cache). Tests that bind
loopback or drive Live need to run outside the agent sandbox.

## Reporting issues

Note the turn (the chat shows it), the browser and the route, and attach `harness timings` output for timing
problems. Logs: `~/_agent_scratch/jobs/harness.log` (server and voice worker), `~/_agent_scratch/probepack/bench.jsonl`
(every Live step of a render).
