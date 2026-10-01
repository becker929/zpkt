"""Voice activity detection for speech boundaries, plus a separate music tagger.

This is the second approach: one component that is purpose-built for speech
edges, and a second, independent component that decides where music is. Speech
regions are stamped on top of the music timeline, because the whole reason to
run a detector rather than a frame classifier is that its edges are sharper.

## Why this is not pyannote

The plan named ``pyannote/segmentation-3.0``. That model is gated on Hugging
Face: an anonymous request for its ``config.yaml`` answers 401, and reaching it
needs an account, an accepted licence and a token. No token exists on this
machine and one cannot be created without the account holder. Rather than skip
the approach, the same role is filled by **Silero VAD**: a small MIT-licensed
recurrent detector that ships its own weights inside its wheel, downloads
nothing, and produces true speech boundaries rather than frame votes. That is
the property the approach was chosen for.

Swap it back by writing a segmenter with the same two methods; nothing above
this module knows which detector is inside.

## The music half

Speech detection alone gives two labels, so music needs its own model. It is
the **Audio Spectrogram Transformer** fine-tuned on AudioSet
(``MIT/ast-finetuned-audioset-10-10-0.4593``). It shares AudioSet's vocabulary
with YAMNet but shares none of its architecture, which is what makes the
comparison in the bakeoff worth anything: where these two agree, two unrelated
models agree.

AST reads a fixed 10.24-second window, so its timeline is coarse, and it is run
with a hop as wide as its window. Overlapping the windows is the only way to get
a finer music grid and it costs a multiple of the whole run; the measurements
behind that choice are on :data:`AST_HOP_S`. Speech, the label that needs
precision, does not come from here at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .audio import decode_blocks, load_untyped
from .audioset import MUSIC, MUSIC_NAMES, OTHER, SPEECH
from .spans import Frame, Span, absorb_short, frames_to_spans, overlay_regions

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    from numpy.typing import NDArray

METHOD = "vad"
SAMPLE_RATE = 16_000

AST_MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
AST_WINDOW_S = 10.24
# The hop is the whole cost of this method, and the number was measured, not
# guessed. Over a 260-second file the AST pass takes 45.7 seconds while the
# voice detector takes 1.3 and decoding takes 0.4. AST's window is fixed at
# 10.24 seconds by its position embeddings, so any finer grid means scoring the
# same audio more than once: a 5.12 s hop doubles the run and a 2.56 s hop
# quadruples it.
#
# The hop is therefore the window. Music gets a 10.24-second grid, which is
# coarse, and that is the honest price of this approach. Speech — the label this
# method exists to place precisely — does not go through here at all. It comes
# from the detector, at the detector's own boundaries.
AST_HOP_S = 10.24
AST_BATCH = 16
MUSIC_THRESHOLD = 0.35
# AST frames are 10.24 s wide, so the default five-frame smoothing window would
# blur over most of a minute. Three is the narrowest window that still removes a
# lone disagreeing frame.
MUSIC_MEDIAN_WIDTH = 3

# Silero reads 512-sample chunks and holds recurrent state, so it is fed in long
# stretches rather than short ones. Ten minutes is 38 MB of float samples.
VAD_BLOCK_S = 600.0
# The detector's own floor is set to the span floor, so its regions survive the
# tidy-up that follows the overlay instead of being folded into a neighbour.
MIN_SPEECH_MS = 500
MIN_SILENCE_MS = 300
SPEECH_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class SpeechRegion:
    """One stretch the detector believes is speech."""

    start_s: float
    end_s: float


class VadMusicSegmenter:
    """Silero VAD for speech, AST for music, combined into one timeline."""

    method = METHOD
    sample_rate = SAMPLE_RATE

    def __init__(self, *, device: str | None = None) -> None:
        import torch  # noqa: PLC0415  (deliberately lazy)
        from silero_vad import load_silero_vad  # noqa: PLC0415
        from transformers import (  # noqa: PLC0415
            ASTForAudioClassification,
            AutoFeatureExtractor,
        )

        self._torch = torch
        self._device = device or _pick_device(torch)
        # Half precision on the GPU, full precision on the CPU. Half is about a
        # fifth faster on Apple's GPU and the labels it produces are the same;
        # CPU kernels for float16 are slower, not faster.
        self._dtype = torch.float16 if self._device == "mps" else torch.float32
        self._vad: Any = load_silero_vad()
        model = load_untyped(
            ASTForAudioClassification.from_pretrained, AST_MODEL, dtype=self._dtype
        )
        self._ast: Any = model.to(self._device).eval()
        self._features: Any = load_untyped(
            AutoFeatureExtractor.from_pretrained, AST_MODEL
        )
        id2label = self._ast.config.id2label
        self._music_indices = [
            index
            for index, name in sorted(id2label.items())
            if str(name) in MUSIC_NAMES
        ]
        self._music_names = [str(id2label[i]) for i in self._music_indices]
        # A tensor on the device, not a Python list. Indexing a GPU tensor with
        # a list falls back to the CPU, which means a full copy off the GPU for
        # every batch.
        self._music_index_tensor = torch.tensor(
            self._music_indices, dtype=torch.long, device=self._device
        )

    def describe(self) -> str:
        return (
            f"Silero VAD + AST AudioSet music tagger "
            f"({len(self._music_indices)} music classes, device={self._device})"
        )

    def segment(self, path: Path, duration_s: float | None = None) -> list[Span]:
        """Music timeline first, speech regions punched in on top."""
        music_frames = self.music_frames(path)
        base = frames_to_spans(music_frames, median_width=MUSIC_MEDIAN_WIDTH)
        if not base:
            return []
        if duration_s is not None and base[-1].end_s > duration_s:
            last = base[-1]
            base[-1] = Span(
                min(last.start_s, duration_s),
                duration_s,
                last.label,
                last.confidence,
                last.detail,
            )
        speech = self.speech_regions(path)
        stamped = overlay_regions(
            base, [(r.start_s, r.end_s, None) for r in speech], SPEECH
        )
        # Stamping speech into the music timeline can leave a sliver of music
        # between two sentences. The same floor that applies to the frame-based
        # classifiers applies here.
        return absorb_short(stamped)

    def speech_regions(self, path: Path) -> list[SpeechRegion]:
        """Detected speech, in seconds, with the detector's own boundaries.

        The file is read in long blocks and the timestamps are shifted back into
        file time. Two regions that meet exactly at a block seam are fused, so a
        sentence that straddles a seam is one region rather than two.
        """
        from silero_vad import get_speech_timestamps  # noqa: PLC0415

        torch = self._torch
        block_samples = int(VAD_BLOCK_S * SAMPLE_RATE)
        regions: list[SpeechRegion] = []
        for start_sample, block in decode_blocks(
            path, sample_rate=SAMPLE_RATE, block_samples=block_samples
        ):
            if len(block) < 512:
                continue
            self._vad.reset_states()
            stamps = get_speech_timestamps(
                torch.from_numpy(block),
                self._vad,
                sampling_rate=SAMPLE_RATE,
                threshold=SPEECH_THRESHOLD,
                min_speech_duration_ms=MIN_SPEECH_MS,
                min_silence_duration_ms=MIN_SILENCE_MS,
                return_seconds=False,
            )
            offset = start_sample / SAMPLE_RATE
            for stamp in stamps:
                start = offset + int(stamp["start"]) / SAMPLE_RATE
                end = offset + int(stamp["end"]) / SAMPLE_RATE
                if regions and start - regions[-1].end_s < 0.05:
                    regions[-1] = SpeechRegion(regions[-1].start_s, end)
                else:
                    regions.append(SpeechRegion(start, end))
        return regions

    def music_frames(self, path: Path) -> list[Frame]:
        """Music-or-not for every ``AST_HOP_S`` slice of the file.

        Each slice takes the highest music score among the windows that cover
        it, so a slice that sits at the edge of a musical passage is still
        judged by the window that saw the music.
        """
        import numpy as np  # noqa: PLC0415

        window = int(AST_WINDOW_S * SAMPLE_RATE)
        hop = int(AST_HOP_S * SAMPLE_RATE)
        per_hop: list[float] = []
        per_hop_name: list[str] = []

        hops_in_window = max(1, int(round(AST_WINDOW_S / AST_HOP_S)))
        batch: list[NDArray[np.float32]] = []
        batch_index: list[int] = []

        def flush() -> None:
            if not batch:
                return
            scores, names = self._score_music(batch)
            for slot, score, name in zip(batch_index, scores, names, strict=True):
                for k in range(hops_in_window):
                    position = slot + k
                    while len(per_hop) <= position:
                        per_hop.append(0.0)
                        per_hop_name.append("")
                    if score > per_hop[position]:
                        per_hop[position] = score
                        per_hop_name[position] = name
            batch.clear()
            batch_index.clear()

        for start_sample, block in decode_blocks(
            path,
            sample_rate=SAMPLE_RATE,
            block_samples=window,
            overlap_samples=window - hop,
        ):
            if len(block) < SAMPLE_RATE // 10:  # under 0.1 s of audio
                continue
            batch.append(block)
            batch_index.append(start_sample // hop)
            if len(batch) >= AST_BATCH:
                flush()
        flush()

        return [
            Frame(
                start_s=i * AST_HOP_S,
                end_s=(i + 1) * AST_HOP_S,
                label=MUSIC if score >= MUSIC_THRESHOLD else OTHER,
                confidence=score if score >= MUSIC_THRESHOLD else 1.0 - score,
                detail=per_hop_name[i] if score >= MUSIC_THRESHOLD else None,
            )
            for i, score in enumerate(per_hop)
        ]

    def _score_music(
        self, windows: list["NDArray[np.float32]"]
    ) -> tuple[list[float], list[str]]:
        """Highest music-class probability in each window, and which class."""
        torch = self._torch
        inputs = self._features(
            [w.astype("float32") for w in windows],
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device).to(self._dtype) for k, v in inputs.items()}
        with torch.no_grad():
            logits = self._ast(**inputs).logits
            music = logits.float().index_select(1, self._music_index_tensor)
            best = torch.max(torch.sigmoid(music), dim=1)
        best_values = best.values.cpu()
        best_indices = best.indices.cpu()
        return (
            [float(v) for v in best_values],
            [self._music_names[int(i)] for i in best_indices],
        )


def _pick_device(torch: Any) -> str:
    """MPS when Apple's GPU is there, CUDA when it is not, CPU otherwise."""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
