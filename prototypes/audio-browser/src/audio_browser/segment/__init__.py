"""Stage 3: split a sound into spans and label each one.

Three classifiers, one table. Each writes rows into ``span`` with its own
``method``, so the interface can switch between them and show where they
disagree. Picking one is the point of the bakeoff, not a decision made here.

* :mod:`.yamnet` — YAMNet over AudioSet's 521 classes. The baseline.
* :mod:`.vad` — Silero VAD for speech edges, AST for music. Substituted for
  pyannote, which is gated behind a Hugging Face licence no token here can
  accept; :mod:`.vad` explains that in full.
* :mod:`.clap` — CLAP zero-shot against written descriptions.

The pure parts are :mod:`.spans` and :mod:`.audioset`. They import no model and
open no file, and they hold every decision about how frames become spans.
Importing this package pulls in no machine-learning library; each classifier
imports its own inside its constructor.
"""

from __future__ import annotations

from .audioset import LABELS, MUSIC, OTHER, SPEECH, label_for
from .spans import (
    MEDIAN_WIDTH,
    MIN_SPAN_S,
    Frame,
    Span,
    absorb_short,
    agreement_seconds,
    dominant_label,
    frames_to_spans,
    label_histogram,
    median_labels,
    merge_frames,
    overlay_regions,
    spans_from_regions,
)

__all__ = [
    "LABELS",
    "MEDIAN_WIDTH",
    "MIN_SPAN_S",
    "MUSIC",
    "OTHER",
    "SPEECH",
    "Frame",
    "Span",
    "absorb_short",
    "agreement_seconds",
    "dominant_label",
    "frames_to_spans",
    "label_for",
    "label_histogram",
    "median_labels",
    "merge_frames",
    "overlay_regions",
    "spans_from_regions",
]
