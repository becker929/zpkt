"""YAMNet: the baseline classifier.

YAMNet is a small MobileNet trained on AudioSet. It reads 16 kHz mono audio and
emits a 521-way score vector every 0.48 seconds. It is the reference the other
two approaches are judged against because it is fast, needs no key and no
licence, and covers the whole AudioSet vocabulary.

**How a frame gets one of three labels.** Each frame's 521 scores are split into
the speech group, the music group and everything else, using the mapping in
:mod:`audio_browser.segment.audioset`. The frame takes the label of whichever
group holds the single highest score, and that score is its confidence. The
winning group's top class becomes the frame's ``detail``.

The maximum is used rather than the sum on purpose. The music group holds 153
classes and the speech group holds 9, so a sum would hand almost every frame to
music regardless of what the audio contains.

**Frame width.** YAMNet's window is 0.96 seconds but its hop is 0.48, so the
windows overlap. Frames here are one hop wide and tile the file without gaps,
which is what the span merger needs. The classification behind each frame still
looks at the wider window.

TensorFlow is imported inside the class, not at module import. Importing it
costs several seconds and pulls in a large native library, and the CLI must stay
fast for the commands that never classify anything.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .audio import decode_blocks
from .audioset import label_for
from .spans import Frame, Span, frames_to_spans

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    from numpy.typing import NDArray

METHOD = "yamnet"
SAMPLE_RATE = 16_000
HOP_S = 0.48
WINDOW_S = 0.96
HOP_SAMPLES = int(HOP_S * SAMPLE_RATE)  # 7,680
# YAMNet needs 0.975 s of audio before it emits a first score. The extra samples
# beyond one hop are what a block has to carry over from the block before it.
LEAD_SAMPLES = 15_600 - HOP_SAMPLES
BLOCK_HOPS = 125  # 60 seconds of advance per block
MODEL_URL = "https://tfhub.dev/google/yamnet/1"

# Where tensorflow_hub unpacks the model. Left to itself it uses the system
# temporary directory, which macOS clears; that would re-download 17 MB on every
# reboot. A cache under the user's home outlives that.
DEFAULT_CACHE = Path.home() / ".cache" / "audio-browser" / "tfhub"


class YamnetSegmenter:
    """Classify a file into spans with YAMNet."""

    method = METHOD
    sample_rate = SAMPLE_RATE

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        cache = cache_dir or DEFAULT_CACHE
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TFHUB_CACHE_DIR", str(cache))

        import tensorflow_hub as hub  # noqa: PLC0415  (deliberately lazy)

        self._model: Any = hub.load(MODEL_URL)
        self._class_names = _read_class_map(
            Path(str(self._model.class_map_path().numpy().decode()))
        )
        self._labels = [label_for(name) for name in self._class_names]
        self._groups = _group_indices(self._labels)

    def describe(self) -> str:
        return f"YAMNet ({len(self._class_names)} AudioSet classes, CPU)"

    def segment(self, path: Path, duration_s: float | None = None) -> list[Span]:
        """Return the spans of one file."""
        spans = frames_to_spans(list(self.frames(path)))
        if duration_s is not None and spans and spans[-1].end_s > duration_s:
            last = spans[-1]
            spans[-1] = Span(
                min(last.start_s, duration_s),
                duration_s,
                last.label,
                last.confidence,
                last.detail,
            )
        return spans

    def frames(self, path: Path) -> list[Frame]:
        """Classify every 0.48 s frame of a file.

        Blocks overlap by one window's lead-in, so the frame grid is unbroken
        across block boundaries and no audio is skipped at a seam.
        """
        import numpy as np

        block_samples = BLOCK_HOPS * HOP_SAMPLES + LEAD_SAMPLES
        out: list[Frame] = []
        next_frame = 0
        for start_sample, block in decode_blocks(
            path,
            sample_rate=SAMPLE_RATE,
            block_samples=block_samples,
            overlap_samples=LEAD_SAMPLES,
        ):
            if len(block) < 400:  # shorter than one mel frame; nothing to score
                continue
            scores = np.asarray(self._model(block)[0])
            base = start_sample // HOP_SAMPLES
            for i in range(scores.shape[0]):
                index = base + i
                if index < next_frame:
                    continue  # already produced by the previous block
                out.append(self._frame(index, scores[i]))
                next_frame = index + 1
        return out

    def _frame(self, index: int, scores: "NDArray[np.float32]") -> Frame:
        label, confidence, detail = self.classify_scores(scores)
        start = index * HOP_S
        return Frame(
            start_s=start,
            end_s=start + HOP_S,
            label=label,
            confidence=confidence,
            detail=detail,
        )

    def classify_scores(
        self, scores: "NDArray[np.float32]"
    ) -> tuple[str, float, str]:
        """Reduce one 521-way score vector to a label, a score and a class name."""
        import numpy as np

        best_label = ""
        best_score = -1.0
        best_name = ""
        for label, indices in self._groups.items():
            group = scores[indices]
            local = int(np.argmax(group))
            value = float(group[local])
            if value > best_score:
                best_score = value
                best_label = label
                best_name = self._class_names[indices[local]]
        return best_label, best_score, best_name


def _read_class_map(path: Path) -> list[str]:
    with path.open(newline="") as fh:
        return [row["display_name"] for row in csv.DictReader(fh)]


def _group_indices(labels: list[str]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, []).append(index)
    return groups
