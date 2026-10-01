"""CLAP zero-shot: classify by describing the sound in words.

CLAP puts audio and text in one embedding space. To classify a window, embed it,
embed a list of sentences, and see which sentence it sits closest to. Nothing is
trained and nothing is fine-tuned. Changing the taxonomy means editing the list
of sentences in :data:`PROMPTS`, which is the property that makes this approach
worth carrying: the other two can only ever emit AudioSet's vocabulary.

## Which checkpoint, and why not the one the plan named

The plan named ``laion/larger_clap_music``, the checkpoint explored in
``clap-poc/``. It does not work for this task, and that was measured rather than
assumed. On five files from this collection — two spoken, two musical, one
foley — every cosine similarity it produces sits between 0.002 and 0.009, and
the ranking of the prompts is the same for all five: a speech recording and a
music render are indistinguishable to it. The same test on
``laion/larger_clap_general`` spreads the similarities across roughly -0.21 to
+0.21 and puts "the sound of music" first for both music renders.

``larger_clap_music`` is a music-only fine-tune. Its audio tower still separates
these recordings from each other, but its text tower has collapsed for
general-purpose sentences, and zero-shot classification needs both. So this
module uses ``laion/larger_clap_general``. The taxonomy, which is the reason
this approach is in the bakeoff at all, is unaffected.

CLAP code is copied rather than imported from ``clap-poc/``, because projects in
this repo do not import across each other.

## Scoring

Every prompt is embedded once, at construction. A window's cosine similarity to
each prompt is divided by a temperature and turned into a distribution with a
softmax over all prompts. The probabilities of the prompts in a group are then
summed. The group with the most probability mass wins, and the strongest single
prompt in it becomes the span's ``detail``.

The temperature is set here rather than taken from the checkpoint. CLAP normally
carries its own trained ``logit_scale``, but in these converted checkpoints it
comes out at about 1.03 instead of the usual double figures, which would flatten
every distribution to uniform no matter what the audio held.

Several prompts per label, rather than one, is deliberate. A single sentence
makes the result hostage to its phrasing; a handful spreads that risk. Summing
within a group rather than taking the group maximum means "music" gets credit
for being *somewhat* like each of several musical descriptions, which is the
usual case for a rough studio recording.

## Boundaries

CLAP reads a 10-second window. It is run with a shorter hop, and each hop takes
the average distribution of the windows covering it, but the finest edge it can
resolve is still one hop. It is the weakest of the three at boundaries and the
report says so with numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .audio import decode_blocks, load_untyped
from .audioset import MUSIC, OTHER, SPEECH
from .spans import Frame, Span, frames_to_spans

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np
    from numpy.typing import NDArray

METHOD = "clap"
MODEL_NAME = "laion/larger_clap_general"
SAMPLE_RATE = 48_000
WINDOW_S = 10.0
HOP_S = 2.5
BATCH = 8
# Similarities from this checkpoint span about 0.4 end to end. Dividing by 0.05
# turns that into roughly eight units of logit, which is enough for the softmax
# to commit to an answer without saturating on a near-tie.
TEMPERATURE = 0.05

# The taxonomy. Edit this and re-run; there is nothing else to change.
PROMPTS: dict[str, tuple[str, ...]] = {
    SPEECH: (
        "a person talking",
        "someone speaking into a microphone",
        "a spoken voice memo",
        "a conversation between people",
    ),
    MUSIC: (
        "music playing",
        "a musical instrument being played",
        "a song with a beat",
        "an electronic music track",
    ),
    OTHER: (
        "silence, an empty recording",
        "background noise and room tone",
        "a single sound effect",
        "machinery, footsteps or other everyday noise",
    ),
}


class ClapSegmenter:
    """Classify a file into spans by scoring it against written descriptions."""

    method = METHOD
    sample_rate = SAMPLE_RATE

    def __init__(
        self,
        *,
        device: str | None = None,
        prompts: dict[str, tuple[str, ...]] | None = None,
        hop_s: float = HOP_S,
        temperature: float = TEMPERATURE,
    ) -> None:
        import torch  # noqa: PLC0415  (deliberately lazy)
        from transformers import ClapModel, ClapProcessor  # noqa: PLC0415

        self._torch = torch
        self._device = device or _pick_device(torch)
        self._hop_s = hop_s
        self._temperature = temperature
        self._prompts = prompts or PROMPTS
        self._flat = [
            (label, text) for label, texts in self._prompts.items() for text in texts
        ]
        self._model: Any = (
            load_untyped(ClapModel.from_pretrained, MODEL_NAME).to(self._device).eval()
        )
        self._processor: Any = load_untyped(
            ClapProcessor.from_pretrained, MODEL_NAME
        )
        self._text_features = self._embed_text([text for _, text in self._flat])

    def describe(self) -> str:
        return (
            f"CLAP zero-shot {MODEL_NAME} "
            f"({len(self._flat)} prompts, hop {self._hop_s}s, device={self._device})"
        )

    def segment(self, path: Path, duration_s: float | None = None) -> list[Span]:
        spans = frames_to_spans(self.frames(path))
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
        """One frame per hop, labelled by the prompts the audio matches."""
        import numpy as np  # noqa: PLC0415

        window = int(WINDOW_S * SAMPLE_RATE)
        hop = int(self._hop_s * SAMPLE_RATE)
        hops_per_window = max(1, int(round(WINDOW_S / self._hop_s)))

        totals: list[NDArray[np.float64]] = []
        counts: list[int] = []

        def add(slot: int, distribution: "NDArray[np.float64]") -> None:
            for k in range(hops_per_window):
                position = slot + k
                while len(totals) <= position:
                    totals.append(np.zeros(len(self._flat)))
                    counts.append(0)
                totals[position] += distribution
                counts[position] += 1

        batch: list[NDArray[np.float32]] = []
        slots: list[int] = []

        def flush() -> None:
            if not batch:
                return
            for slot, distribution in zip(
                slots, self._probabilities(batch), strict=True
            ):
                add(slot, distribution)
            batch.clear()
            slots.clear()

        for start_sample, block in decode_blocks(
            path,
            sample_rate=SAMPLE_RATE,
            block_samples=window,
            overlap_samples=window - hop,
        ):
            if len(block) < SAMPLE_RATE // 10:
                continue
            batch.append(block)
            slots.append(start_sample // hop)
            if len(batch) >= BATCH:
                flush()
        flush()

        frames: list[Frame] = []
        for i, total in enumerate(totals):
            if counts[i] == 0:  # pragma: no cover - add() always increments
                continue
            label, confidence, detail = self._decide(total / counts[i])
            frames.append(
                Frame(
                    start_s=i * self._hop_s,
                    end_s=(i + 1) * self._hop_s,
                    label=label,
                    confidence=confidence,
                    detail=detail,
                )
            )
        return frames

    def _decide(
        self, distribution: "NDArray[np.float64]"
    ) -> tuple[str, float, str]:
        """Sum prompt probabilities per label; the fullest group wins."""
        per_label: dict[str, float] = {}
        best_prompt: dict[str, tuple[float, str]] = {}
        for (label, text), probability in zip(
            self._flat, distribution, strict=True
        ):
            value = float(probability)
            per_label[label] = per_label.get(label, 0.0) + value
            if value > best_prompt.get(label, (-1.0, ""))[0]:
                best_prompt[label] = (value, text)
        label = max(per_label.items(), key=lambda kv: kv[1])[0]
        return label, per_label[label], best_prompt[label][1]

    def _probabilities(
        self, windows: list["NDArray[np.float32]"]
    ) -> list["NDArray[np.float64]"]:
        import numpy as np  # noqa: PLC0415

        torch = self._torch
        inputs = self._processor(
            audio=[w.astype("float32") for w in windows],
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            audio_features = _pooled(self._model.get_audio_features(**inputs))
            logits = (audio_features @ self._text_features.T) / self._temperature
            probabilities = torch.softmax(logits, dim=-1).cpu().numpy()
        return [np.asarray(row, dtype=np.float64) for row in probabilities]

    def _embed_text(self, texts: list[str]) -> Any:
        torch = self._torch
        inputs = self._processor(text=texts, return_tensors="pt", padding=True)
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            return _pooled(self._model.get_text_features(**inputs))


def _pooled(output: Any) -> Any:
    """The embedding out of a CLAP feature call.

    ``transformers`` changed these methods to return a model-output object whose
    ``pooler_output`` holds the projected, already unit-length embedding. Older
    versions returned the tensor itself. Accepting both keeps the classifier
    working across that change.
    """
    return getattr(output, "pooler_output", output)


def _pick_device(torch: Any) -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
