# studio's speech models: the benchmark and the choice (plan V1)

Speech runs on the Mac mini (Apple M6, 16 GB) in its own process, `lib/voice` (`voice serve`). This page records
how its two models were chosen and tuned. The bench scripts and test sets live outside the repo, in
`~/_agent_scratch/voice-bench/` (stt/ and kokoro/); `lib/voice/bench/stt_turns.py` re-runs the speech-to-text
check on the shipped code.

**Choice:** speech-to-text is **Parakeet TDT 0.6B v3** on MLX (fp32), gated by **Silero VAD v6**; text-to-speech is
**Kokoro 82M** through ONNX Runtime (`kokoro-onnx`, fp32 by default, int8 one setting away).

## Speech to text

### Test set

240 files: 40 utterances in 6 conditions (clean; brown noise at 20 and 10 dB SNR; pink at 20 and 10; babble at
15). Nine macOS voices (three of them robotic, reported apart). Four categories: short commands that end in
"tomato", long multi-sentence turns that end in it with pauses inside, near misses ("potato", "tomorrow",
"tomatoes are...") and turns with no stop word. The vocabulary is studio's: kick, hi-hat, dB, A/B, BPM, bars.

### Whole-file accuracy and speed

WER % (normalised for numbers and spellings), and stop-word recall when the whole file is transcribed:

| engine | clean | noise avg (brown/pink) | babble15 | clean, natural voices | stop recall | stop false positives |
|---|---|---|---|---|---|---|
| Apple SpeechAnalyzer | 5.7 | 8.9 | 43.9 | 3.9 | 85% | 0/96 |
| mlx-whisper small.en | 4.6 | 6.4 | 5.7 | 3.7 | 99% | 0/96 |
| mlx-whisper large-v3-turbo | 4.4 | 5.8 | 4.2 | 2.8 | 100% | 0/96 |
| whisper.cpp small.en (Core ML) | 4.4 | 5.8 | 6.4 | 3.7 | 98% | 0/96 |
| Parakeet TDT 0.6B v2 | 5.5 | 6.3 | 37.3 | 3.5 | 92% | 0/96 |
| **Parakeet TDT 0.6B v3** | **4.4** | **5.4** | 18.3 | **3.5** | 94% | 0/96 |

| engine | warm call: fixed + per audio-second | median call (5-14 s file) | peak memory |
|---|---|---|---|
| Apple SpeechAnalyzer | 22 ms + 6.5 ms | 64 ms | 7 MB |
| mlx-whisper small.en | 33 ms + 8.7 ms | 84 ms | 2.0 GB |
| mlx-whisper large-v3-turbo | 242 ms + 8.2 ms | 293 ms | 2.8 GB |
| Parakeet v3, fp32 | 29 ms + 5.7 ms | 64 ms | 8.0 GB uncapped, 3.4 GB with the cache capped at 512 MB |

Whisper turbo is the most accurate but costs ~240 ms a call, which a turn pays at every check. Apple's model is the
lightest but misses the stop word one time in seven and falls apart in babble. Parakeet v3 is as accurate as the
best Whisper on everything except babble, at a quarter of the cost; babble is handled by the gate below.

### Streaming: how a turn ends

A turn ends only when the transcript's last word is the stop word; pauses never end it. The shipped design
(`voice/stt.py`):

- Silero VAD per 32 ms frame, behind a causal level gate (frames 12 dB under the talker's running level count as
  silence: a radio or a passenger does not hold the turn open), with hysteresis (on 0.5, off 0.35).
- After speech, 150 ms of silence: transcribe the turn so far; if it ends with the stop word, that is the final.
- Captions every 600 ms of open speech. A stable tail (two transcripts 0.5 s apart, both ending with the stop word,
  otherwise equal) also ends a turn, for when noise keeps the VAD open. One more look over the whole turn after
  1 s of silence, if the close-time check missed.
- The model's input is gated too: audio that is not the main talker is attenuated by 40 dB, and 0.3 s of silence is
  appended, which gives the last word right context at no cost in waiting.
- Matching the stop word: exact forms, one edit away, or split across two or three words ("to mato"); a phonetic
  rule accepts "tomedo" and "to motto" and rejects "to make", "to mute", "potato", "tomorrow", "tomatillo".

The shipped code over all 240 files, fed in 40 ms frames in real time (`bench/stt_turns.py`):

| | result |
|---|---|
| stop-word recall | 139/144 (131/132 for the natural voices) |
| false ends (a final with no stop word, or before it) | 0/96 |
| latency after "tomato" ends, median / p90 / max | 257 / 743 / 1304 ms |
| median latency: clean, brown/pink 20 dB, 10 dB, babble | 214, 219-229, 285-317, 852 ms |
| word error rate of the final text | 4.6% |

Tuning (close delay 150-400 ms, caption cadence 400 or 600 ms) moved latency more than accuracy; 150 ms and 600 ms
are the best trade. The five misses are robotic voices in babble.

Memory: MLX's buffer cache grows to ~5.4 GB over 720 calls unless capped; the worker caps it at 512 MB (peak
footprint 3.4 GB, the same speed). fp32 weights are faster than fp16 here (28 against 61 ms fixed cost a call).

## Text to speech

Kokoro 82M in every runtime that runs it on a Mac, timed from a warm process (TTFA: time to the first audio):

| runtime | load s | TTFA short | TTFA first chunk | RTF | CPU % | peak memory |
|---|---|---|---|---|---|---|
| FluidAudio v3 (Swift, ANE) | 0.66 | 94 ms | 97 ms | 0.057 | 103 | 2.7 GB |
| mlx-audio (MLX) | 1.99 | 127 ms | 132 ms | 0.047 | 40 | 9.5 GB |
| PyTorch, MPS | 2.81 | 330 ms | 355 ms | 0.067 | 27 | 3.0 GB |
| **kokoro-onnx fp32, CPU** | 1.48 | 435 ms | 520 ms | 0.225 | 570 | 1.6 GB |
| kokoro-onnx int8, CPU | 1.70 | 391 ms | 260 ms | 0.115 | 550 | 1.5 GB |
| sherpa-onnx fp32, CPU | 0.38 | 584 ms | 509 ms | 0.244 | 395 | 0.8 GB |

The ONNX build is not the fastest: FluidAudio (Swift, on the Neural Engine) gets the first audio out four times
sooner, and MLX three times. ONNX is shipped because it is a pure Python dependency with no build step and no
GPU contention with Parakeet (which owns the GPU while you talk); at 0.2 of real time it stays ahead of playback,
and speech is cut into sentences, so the first sentence is what you wait for. `VOICE_TTS_MODEL=int8` halves that
wait. If the first-audio time measured on the phone (`harness timings`, `first_audio`) is too long, the next step
is the FluidAudio worker (built in the bench, not yet in `lib/voice`).

## Claude and audio

Plan V1 asked whether Claude accepts streamed audio input. It does not: the Messages API and Claude Code take text,
images and documents, not audio (an open feature request, anthropics/anthropic-sdk-python#1198). Speech is
transcribed on the Mac and Claude gets text; the recording is kept with the message for replay.

## Measuring turns (plan V1)

Every turn records its stages (`studio/timing.py`): on the Mac, ms since the mic was offered (first words, stop
word, first narration, first text, agent done, first audio, music ready, responded); on the phone, durations it
measured (mic open, route settle, first speech audio, music first play). Each turn is tagged with its number since
the server started, the browser, and the mic's device label (the phone's own or a Bluetooth route).

    uv run --project lib/harness harness timings      # medians per stage: first vs later turns, Safari vs Chrome,
                                                       # phone mic and speaker vs Bluetooth
