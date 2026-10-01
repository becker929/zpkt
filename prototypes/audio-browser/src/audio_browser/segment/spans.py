"""Turning a sequence of frame labels into a small set of spans.

This module is the pure core of stage 3. It holds no models, opens no files and
touches no database. Every classifier produces frames; this code turns frames
into the spans the waveform draws.

Three steps, in order.

**Smooth.** A categorical median filter replaces each frame's label with the
most common label in a window centred on it. Ties go to the frame's own label,
so smoothing never invents a label the frame did not already have.

**Merge.** Runs of frames that share a label become one span. The span's
confidence is the mean confidence of its frames. Its ``detail`` is the most
common fine-grained class among them, which is why a stretch of music can say
"drum kit" rather than only "music".

**Absorb.** A span shorter than the floor is folded into a neighbour instead of
being deleted. Deleting would leave a hole in the timeline, and a waveform with
holes in it is harder to read than one with slightly wrong edges. The shorter
span joins its longer neighbour; on a tie it joins the one before it. A file
that is entirely shorter than the floor keeps its single span, because the
alternative is returning nothing at all for a short sound.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .audioset import LABELS, OTHER

MIN_SPAN_S = 0.5
MEDIAN_WIDTH = 5


@dataclass(frozen=True, slots=True)
class Frame:
    """One fixed-width classification window.

    ``confidence`` is the classifier's score for ``label`` in this window, on
    0..1. ``detail`` is the finer class behind the decision, or None when the
    classifier has no finer vocabulary.
    """

    start_s: float
    end_s: float
    label: str
    confidence: float
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Span:
    """One labelled region, as it is written to the ``span`` table."""

    start_s: float
    end_s: float
    label: str
    confidence: float | None
    detail: str | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def median_labels(labels: Sequence[str], width: int = MEDIAN_WIDTH) -> list[str]:
    """Smooth a label sequence with a categorical median (mode) filter.

    ``width`` is forced odd and at least 1, so the window is always centred.
    A width of 1 returns the input unchanged. The window is clipped at both
    ends rather than padded, so the first and last frames are smoothed over
    whatever neighbours exist.
    """
    if width < 1:
        raise ValueError("width must be positive")
    if width % 2 == 0:
        width += 1
    if width == 1 or not labels:
        return list(labels)

    half = width // 2
    n = len(labels)
    out: list[str] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        counts = Counter(labels[lo:hi])
        best = max(counts.values())
        # Ties go to the frame's own label when it is among the winners, so
        # smoothing can only ever replace a label with a genuinely commoner one.
        own = labels[i]
        if counts[own] == best:
            out.append(own)
        else:
            out.append(min(name for name, c in counts.items() if c == best))
    return out


def merge_frames(frames: Sequence[Frame]) -> list[Span]:
    """Collapse runs of same-labelled frames into spans.

    Frames are taken in the order given. No smoothing happens here; run
    :func:`median_labels` first if you want it.
    """
    spans: list[Span] = []
    run: list[Frame] = []

    def flush() -> None:
        if run:
            spans.append(_span_of(run))
            run.clear()

    for frame in frames:
        if run and frame.label != run[-1].label:
            flush()
        run.append(frame)
    flush()
    return spans


def absorb_short(spans: Sequence[Span], min_s: float = MIN_SPAN_S) -> list[Span]:
    """Fold spans shorter than ``min_s`` into a neighbour, repeatedly.

    The shortest offender goes first, which keeps the result independent of the
    order the spans happen to sit in. When only one span is left it is kept,
    however short it is.

    The implementation is a linked list plus a heap rather than a scan of the
    list on every pass. A twelve-hour recording can arrive here as tens of
    thousands of frame-level spans, and re-scanning the list each time one is
    absorbed would be quadratic: minutes of work for one file. This is
    ``n log n``. Entries in the heap are stamped with the version of the span
    they describe, so a stale entry is recognised and dropped rather than
    removed eagerly.
    """
    items = list(spans)
    if min_s <= 0 or len(items) < 2:
        return items

    starts = [s.start_s for s in items]
    ends = [s.end_s for s in items]
    labels = [s.label for s in items]
    confidences = [s.confidence for s in items]
    details = [s.detail for s in items]
    previous = list(range(-1, len(items) - 1))
    following = list(range(1, len(items) + 1))
    following[-1] = -1
    alive = [True] * len(items)
    version = [0] * len(items)
    live = len(items)

    heap = [(ends[i] - starts[i], 0, i) for i in range(len(items))]
    heapq.heapify(heap)

    while heap and live > 1:
        duration, stamp, i = heapq.heappop(heap)
        if not alive[i] or stamp != version[i]:
            continue
        if duration >= min_s:
            break
        left, right = previous[i], following[i]
        if left < 0 and right < 0:  # pragma: no cover - live > 1 prevents this
            break
        take_left = right < 0 or (
            left >= 0 and (ends[left] - starts[left]) >= (ends[right] - starts[right])
        )
        keep = left if take_left else right
        # The absorbed span's time goes to the neighbour; the neighbour's label,
        # confidence and detail are what survive.
        starts[keep] = min(starts[keep], starts[i])
        ends[keep] = max(ends[keep], ends[i])
        alive[i] = False
        live -= 1
        if take_left:
            following[left] = right
            if right >= 0:
                previous[right] = left
        else:
            previous[right] = left
            if left >= 0:
                following[left] = right
        version[keep] += 1
        heapq.heappush(heap, (ends[keep] - starts[keep], version[keep], keep))

    return [
        Span(starts[i], ends[i], labels[i], confidences[i], details[i])
        for i in range(len(items))
        if alive[i]
    ]


def frames_to_spans(
    frames: Sequence[Frame],
    *,
    median_width: int = MEDIAN_WIDTH,
    min_span_s: float = MIN_SPAN_S,
) -> list[Span]:
    """Smooth, merge, then absorb. The whole pipeline in one call."""
    if not frames:
        return []
    smoothed = median_labels([f.label for f in frames], median_width)
    relabelled = [
        Frame(
            start_s=f.start_s,
            end_s=f.end_s,
            label=new,
            confidence=f.confidence,
            # A frame whose label was rewritten by the filter no longer stands
            # behind its own fine-grained class, so that class is dropped.
            detail=f.detail if new == f.label else None,
        )
        for f, new in zip(frames, smoothed, strict=True)
    ]
    return absorb_short(merge_frames(relabelled), min_span_s)


def spans_from_regions(
    regions: Sequence[tuple[float, float, str, float | None]],
    duration_s: float,
    *,
    fill_label: str = OTHER,
) -> list[Span]:
    """Turn a list of detected regions into a gap-free timeline.

    A boundary detector reports only the regions it found. The waveform wants
    the whole file covered, so the gaps between regions become ``fill_label``
    spans with no confidence. Regions are sorted and clipped to
    ``[0, duration_s]``; overlapping regions are truncated so the earlier one
    wins its overlap.
    """
    ordered = sorted(
        (
            (max(0.0, start), min(duration_s, end), label, score)
            for start, end, label, score in regions
        ),
        key=lambda r: (r[0], r[1]),
    )
    out: list[Span] = []
    cursor = 0.0
    for start, end, label, score in ordered:
        start = max(start, cursor)
        if end <= start:
            continue
        if start > cursor:
            out.append(Span(cursor, start, fill_label, None, None))
        out.append(Span(start, end, label, score, None))
        cursor = end
    if cursor < duration_s:
        out.append(Span(cursor, duration_s, fill_label, None, None))
    if not out and duration_s > 0:
        out.append(Span(0.0, duration_s, fill_label, None, None))
    return out


def overlay_regions(
    base: Sequence[Span],
    regions: Sequence[tuple[float, float, float | None]],
    label: str,
) -> list[Span]:
    """Stamp ``regions`` onto a timeline, overwriting whatever they cover.

    This is how a boundary detector and a frame classifier are combined. The
    frame classifier lays down a coarse timeline; the detector's regions are
    then punched into it at their own, sharper, edges. Base spans are split
    where a region starts or ends, and base spans wholly inside a region
    disappear.

    Regions are clipped to the base timeline's extent and merged where they
    touch, so the result is still gap-free and still in order.
    """
    if not base:
        return []
    start_limit = base[0].start_s
    end_limit = base[-1].end_s
    merged = _merge_ranges(
        [
            (max(start_limit, s), min(end_limit, e), score)
            for s, e, score in regions
            if min(end_limit, e) > max(start_limit, s)
        ]
    )
    if not merged:
        return list(base)

    # Both lists are in time order, so one pointer walks the regions while the
    # other walks the base spans. Re-scanning every region for every span would
    # be quadratic, and a twelve-hour recording brings thousands of each.
    out: list[Span] = []
    first_live = 0
    for span in base:
        cursor = span.start_s
        k = first_live
        while k < len(merged) and merged[k][1] <= cursor:
            k += 1
        first_live = k  # regions fully behind the cursor can never matter again
        while k < len(merged) and merged[k][0] < span.end_s:
            r_start, r_end, _score = merged[k]
            if r_start > cursor:
                out.append(
                    Span(cursor, r_start, span.label, span.confidence, span.detail)
                )
            cursor = min(span.end_s, r_end)
            if r_end >= span.end_s:
                break
            k += 1
        if cursor < span.end_s:
            out.append(Span(cursor, span.end_s, span.label, span.confidence, span.detail))
    for r_start, r_end, score in merged:
        out.append(Span(r_start, r_end, label, score, None))
    out.sort(key=lambda s: (s.start_s, s.end_s))
    return _join_touching(out)


def _merge_ranges(
    ranges: Sequence[tuple[float, float, float | None]],
) -> list[tuple[float, float, float | None]]:
    """Sort ranges and fuse any that overlap or touch. Scores are averaged."""
    ordered = sorted(ranges, key=lambda r: (r[0], r[1]))
    out: list[tuple[float, float, float | None]] = []
    for start, end, score in ordered:
        if out and start <= out[-1][1]:
            prev_start, prev_end, prev_score = out[-1]
            if prev_score is None:
                fused = score
            elif score is None:
                fused = prev_score
            else:
                fused = (prev_score + score) / 2
            out[-1] = (prev_start, max(prev_end, end), fused)
        else:
            out.append((start, end, score))
    return out


def _join_touching(spans: Sequence[Span]) -> list[Span]:
    """Fuse neighbouring spans that share a label into one."""
    out: list[Span] = []
    for span in spans:
        if out and out[-1].label == span.label and out[-1].end_s >= span.start_s:
            prev = out[-1]
            confidences = [c for c in (prev.confidence, span.confidence) if c is not None]
            out[-1] = Span(
                prev.start_s,
                max(prev.end_s, span.end_s),
                prev.label,
                sum(confidences) / len(confidences) if confidences else None,
                prev.detail or span.detail,
            )
        else:
            out.append(span)
    return out


def label_histogram(spans: Sequence[Span]) -> dict[str, float]:
    """Seconds per label. Every label in :data:`LABELS` is present, even at 0."""
    totals = dict.fromkeys(LABELS, 0.0)
    for span in spans:
        totals[span.label] = totals.get(span.label, 0.0) + span.duration_s
    return totals


def dominant_label(spans: Sequence[Span]) -> str:
    """The label covering the most seconds. ``other`` when there is nothing."""
    totals = label_histogram(spans)
    if not spans:
        return OTHER
    return max(totals.items(), key=lambda kv: (kv[1], kv[0] == OTHER))[0]


def overlaps(
    left: Sequence[Span], right: Sequence[Span]
) -> Iterator[tuple[float, str, str]]:
    """Walk two timelines together, yielding ``(seconds, left, right)``.

    Both lists must be in time order, which every producer here guarantees.
    Only stretches both lists cover are yielded, so a method that stopped early
    does not silently count as disagreement over the tail.

    This is a two-pointer merge rather than a lookup per interval. The whole
    bakeoff comparison runs over hundreds of files, some with thousands of
    spans, and a lookup per interval would make it quadratic in each file.
    """
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        start = max(a.start_s, b.start_s)
        end = min(a.end_s, b.end_s)
        if end > start:
            yield end - start, a.label, b.label
        if a.end_s <= b.end_s:
            i += 1
        else:
            j += 1


def agreement_seconds(
    left: Sequence[Span], right: Sequence[Span]
) -> tuple[float, float]:
    """Seconds where two span lists agree, and seconds they both cover.

    Both are treated as timelines, so the comparison does not care that the two
    methods used different frame sizes.
    """
    agreed = 0.0
    covered = 0.0
    for width, a, b in overlaps(left, right):
        covered += width
        if a == b:
            agreed += width
    return agreed, covered


def _span_of(frames: Sequence[Frame]) -> Span:
    label = frames[0].label
    confidence = sum(f.confidence for f in frames) / len(frames)
    details = Counter(f.detail for f in frames if f.detail is not None)
    detail = details.most_common(1)[0][0] if details else None
    return Span(
        start_s=frames[0].start_s,
        end_s=frames[-1].end_s,
        label=label,
        confidence=confidence,
        detail=detail,
    )


