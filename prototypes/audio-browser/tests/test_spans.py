"""The pure core of stage 3: frames in, spans out.

Nothing here loads a model or opens an audio file. Every test is arithmetic on
labels and times, which is exactly why the merging logic was pulled out of the
classifiers in the first place.
"""

from __future__ import annotations

import pytest

from audio_browser.segment.audioset import MUSIC, OTHER, SPEECH, label_for
from audio_browser.segment.spans import (
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


def frames(labels: str, *, width: float = 1.0, confidence: float = 0.9) -> list[Frame]:
    """Build a frame per character. 's' speech, 'm' music, 'o' other."""
    names = {"s": SPEECH, "m": MUSIC, "o": OTHER}
    return [
        Frame(
            start_s=i * width,
            end_s=(i + 1) * width,
            label=names[c],
            confidence=confidence,
            detail=None,
        )
        for i, c in enumerate(labels)
    ]


def shape(spans: list[Span]) -> list[tuple[float, float, str]]:
    return [(s.start_s, s.end_s, s.label) for s in spans]


# ------------------------------------------------------------------ mapping


def test_speech_classes_map_to_speech() -> None:
    assert label_for("Speech") == SPEECH
    assert label_for("Narration, monologue") == SPEECH
    assert label_for("Whispering") == SPEECH


def test_music_classes_map_to_music() -> None:
    assert label_for("Music") == MUSIC
    assert label_for("Drum kit") == MUSIC
    assert label_for("Techno") == MUSIC


def test_singing_is_music_even_though_the_ontology_files_it_under_voice() -> None:
    """A sung take is music. AudioSet puts Singing under Human voice."""
    assert label_for("Singing") == MUSIC
    assert label_for("Rapping") == MUSIC
    assert label_for("Choir") == MUSIC


def test_everything_else_is_other() -> None:
    assert label_for("Silence") == OTHER
    assert label_for("Laughter") == OTHER
    assert label_for("Walk, footsteps") == OTHER


def test_an_unknown_class_name_is_other_rather_than_an_error() -> None:
    assert label_for("Klaxon of the Thousand Suns") == OTHER


# ------------------------------------------------------------- median filter


def test_a_width_of_one_changes_nothing() -> None:
    assert median_labels(["a", "b", "a"], 1) == ["a", "b", "a"]


def test_an_even_width_is_rounded_up_so_the_window_stays_centred() -> None:
    assert median_labels(["a", "b", "a", "a", "a"], 4) == median_labels(
        ["a", "b", "a", "a", "a"], 5
    )


def test_a_lone_frame_is_smoothed_away() -> None:
    assert median_labels(list("aaabaaa"), 5) == list("aaaaaaa")


def test_a_run_as_wide_as_the_window_survives() -> None:
    assert median_labels(list("aaabbbaaa"), 5) == list("aaabbbaaa")


def test_a_tie_keeps_the_frames_own_label() -> None:
    """With two of each in view, the frame does not change its mind."""
    assert median_labels(list("aabb"), 3)[1] == "a"
    assert median_labels(list("aabb"), 3)[2] == "b"


def test_smoothing_an_empty_sequence_is_empty() -> None:
    assert median_labels([], 5) == []


def test_a_zero_width_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        median_labels(["a"], 0)


# -------------------------------------------------------------------- merge


def test_runs_of_one_label_become_one_span() -> None:
    spans = merge_frames(frames("sssmmm"))
    assert shape(spans) == [(0.0, 3.0, SPEECH), (3.0, 6.0, MUSIC)]


def test_a_spans_confidence_is_the_mean_of_its_frames() -> None:
    two = [
        Frame(0.0, 1.0, SPEECH, 0.4),
        Frame(1.0, 2.0, SPEECH, 0.8),
    ]
    assert merge_frames(two)[0].confidence == pytest.approx(0.6)


def test_a_spans_detail_is_the_commonest_one_among_its_frames() -> None:
    run = [
        Frame(0.0, 1.0, MUSIC, 0.9, "Piano"),
        Frame(1.0, 2.0, MUSIC, 0.9, "Drum kit"),
        Frame(2.0, 3.0, MUSIC, 0.9, "Drum kit"),
    ]
    assert merge_frames(run)[0].detail == "Drum kit"


def test_merging_nothing_gives_nothing() -> None:
    assert merge_frames([]) == []


# ------------------------------------------------------------------- absorb


def test_a_sliver_joins_its_longer_neighbour() -> None:
    spans = [
        Span(0.0, 5.0, SPEECH, 0.9),
        Span(5.0, 5.2, MUSIC, 0.5),
        Span(5.2, 9.0, OTHER, 0.7),
    ]
    assert shape(absorb_short(spans, 0.5)) == [
        (0.0, 5.2, SPEECH),
        (5.2, 9.0, OTHER),
    ]


def test_absorbing_leaves_no_hole_in_the_timeline() -> None:
    spans = absorb_short(
        [
            Span(0.0, 4.0, SPEECH, 0.9),
            Span(4.0, 4.1, MUSIC, 0.5),
            Span(4.1, 4.2, OTHER, 0.5),
            Span(4.2, 10.0, MUSIC, 0.9),
        ],
        0.5,
    )
    assert spans[0].start_s == 0.0
    assert spans[-1].end_s == 10.0
    for before, after in zip(spans, spans[1:]):
        assert before.end_s == after.start_s


def test_the_only_span_survives_however_short_it_is() -> None:
    """A 0.2 second sample must still get a label, not an empty list."""
    spans = absorb_short([Span(0.0, 0.2, MUSIC, 0.9)], 0.5)
    assert shape(spans) == [(0.0, 0.2, MUSIC)]


def test_a_floor_of_zero_absorbs_nothing() -> None:
    spans = [Span(0.0, 0.1, SPEECH, 0.9), Span(0.1, 5.0, MUSIC, 0.9)]
    assert absorb_short(spans, 0.0) == spans


def test_a_sliver_at_the_end_joins_the_span_before_it() -> None:
    spans = absorb_short(
        [Span(0.0, 9.0, MUSIC, 0.9), Span(9.0, 9.1, SPEECH, 0.5)], 0.5
    )
    assert shape(spans) == [(0.0, 9.1, MUSIC)]


# ----------------------------------------------------------- whole pipeline


def test_frame_noise_does_not_survive_the_pipeline() -> None:
    """One misread frame in a wall of music must not become a span."""
    spans = frames_to_spans(frames("mmmmmsmmmmm"), median_width=5, min_span_s=0.5)
    assert shape(spans) == [(0.0, 11.0, MUSIC)]


def test_a_real_change_of_content_does_survive() -> None:
    spans = frames_to_spans(frames("sssssssmmmmmmm"), median_width=5, min_span_s=0.5)
    assert shape(spans) == [(0.0, 7.0, SPEECH), (7.0, 14.0, MUSIC)]


def test_the_pipeline_on_no_frames_is_no_spans() -> None:
    assert frames_to_spans([]) == []


def test_a_relabelled_frame_gives_up_its_fine_grained_class() -> None:
    """The filter overrode this frame, so its own class no longer applies."""
    noisy = frames("mmmmm")
    noisy[2] = Frame(2.0, 3.0, SPEECH, 0.9, "Speech")
    spans = frames_to_spans(noisy, median_width=5, min_span_s=0.5)
    assert len(spans) == 1
    assert spans[0].detail != "Speech"


def test_short_frames_still_produce_spans_at_or_above_the_floor() -> None:
    spans = frames_to_spans(
        frames("ssmmssssssssss", width=0.1), median_width=1, min_span_s=0.5
    )
    assert all(s.duration_s >= 0.5 for s in spans) or len(spans) == 1


# ------------------------------------------------------- regions to a timeline


def test_gaps_between_regions_become_other() -> None:
    spans = spans_from_regions([(2.0, 4.0, SPEECH, 0.9)], 10.0)
    assert shape(spans) == [
        (0.0, 2.0, OTHER),
        (2.0, 4.0, SPEECH),
        (4.0, 10.0, OTHER),
    ]


def test_a_file_with_no_regions_is_one_other_span() -> None:
    assert shape(spans_from_regions([], 3.0)) == [(0.0, 3.0, OTHER)]


def test_regions_are_clipped_to_the_files_length() -> None:
    spans = spans_from_regions([(-1.0, 99.0, SPEECH, 0.5)], 4.0)
    assert shape(spans) == [(0.0, 4.0, SPEECH)]


def test_the_earlier_region_keeps_the_overlap() -> None:
    spans = spans_from_regions(
        [(0.0, 5.0, SPEECH, 0.9), (3.0, 8.0, SPEECH, 0.8)], 8.0
    )
    assert spans[0].start_s == 0.0
    assert spans[-1].end_s == 8.0
    for before, after in zip(spans, spans[1:]):
        assert before.end_s == after.start_s


# ------------------------------------------------------------------ overlay


def test_a_region_punches_through_the_base_timeline() -> None:
    base = [Span(0.0, 10.0, MUSIC, 0.9)]
    spans = overlay_regions(base, [(4.0, 6.0, 0.8)], SPEECH)
    assert shape(spans) == [
        (0.0, 4.0, MUSIC),
        (4.0, 6.0, SPEECH),
        (6.0, 10.0, MUSIC),
    ]


def test_a_region_covering_everything_leaves_only_itself() -> None:
    base = [Span(0.0, 4.0, MUSIC, 0.9), Span(4.0, 10.0, OTHER, 0.5)]
    assert shape(overlay_regions(base, [(0.0, 10.0, None)], SPEECH)) == [
        (0.0, 10.0, SPEECH)
    ]


def test_regions_that_touch_become_one_span() -> None:
    base = [Span(0.0, 10.0, OTHER, 0.5)]
    spans = overlay_regions(base, [(2.0, 4.0, None), (4.0, 6.0, None)], SPEECH)
    assert shape(spans) == [
        (0.0, 2.0, OTHER),
        (2.0, 6.0, SPEECH),
        (6.0, 10.0, OTHER),
    ]


def test_overlay_is_clipped_to_the_base_extent() -> None:
    base = [Span(0.0, 5.0, MUSIC, 0.9)]
    spans = overlay_regions(base, [(-3.0, 30.0, None)], SPEECH)
    assert shape(spans) == [(0.0, 5.0, SPEECH)]


def test_overlaying_nothing_returns_the_base_unchanged() -> None:
    base = [Span(0.0, 5.0, MUSIC, 0.9)]
    assert overlay_regions(base, [], SPEECH) == base


def test_overlaying_onto_nothing_is_nothing() -> None:
    assert overlay_regions([], [(1.0, 2.0, None)], SPEECH) == []


def test_an_overlay_keeps_the_timeline_gap_free() -> None:
    base = [
        Span(0.0, 5.0, MUSIC, 0.9),
        Span(5.0, 10.0, OTHER, 0.6),
        Span(10.0, 20.0, MUSIC, 0.9),
    ]
    spans = overlay_regions(base, [(3.0, 7.0, None), (12.0, 13.0, None)], SPEECH)
    assert spans[0].start_s == 0.0
    assert spans[-1].end_s == 20.0
    for before, after in zip(spans, spans[1:]):
        assert before.end_s == after.start_s


# ------------------------------------------------------------- measurements


def test_the_histogram_counts_seconds_per_label() -> None:
    totals = label_histogram(
        [Span(0.0, 3.0, SPEECH, 0.9), Span(3.0, 4.0, MUSIC, 0.9)]
    )
    assert totals[SPEECH] == 3.0
    assert totals[MUSIC] == 1.0
    assert totals[OTHER] == 0.0


def test_the_dominant_label_is_the_one_holding_the_most_seconds() -> None:
    assert (
        dominant_label([Span(0.0, 3.0, SPEECH, 0.9), Span(3.0, 4.0, MUSIC, 0.9)])
        == SPEECH
    )


def test_an_empty_timeline_is_dominated_by_other() -> None:
    assert dominant_label([]) == OTHER


def test_identical_timelines_agree_completely() -> None:
    spans = [Span(0.0, 3.0, SPEECH, 0.9), Span(3.0, 8.0, MUSIC, 0.9)]
    agreed, covered = agreement_seconds(spans, spans)
    assert agreed == pytest.approx(8.0)
    assert covered == pytest.approx(8.0)


def test_agreement_ignores_how_the_two_methods_chopped_up_time() -> None:
    """One method used 1-second frames, the other used 4. They still agree."""
    fine = [Span(float(i), float(i + 1), MUSIC, 0.9) for i in range(4)]
    coarse = [Span(0.0, 4.0, MUSIC, 0.9)]
    agreed, covered = agreement_seconds(fine, coarse)
    assert agreed == pytest.approx(4.0)
    assert covered == pytest.approx(4.0)


def test_only_the_overlapping_stretch_is_counted() -> None:
    left = [Span(0.0, 10.0, MUSIC, 0.9)]
    right = [Span(0.0, 4.0, MUSIC, 0.9)]
    agreed, covered = agreement_seconds(left, right)
    assert covered == pytest.approx(4.0)
    assert agreed == pytest.approx(4.0)


def test_opposite_labels_agree_on_nothing() -> None:
    agreed, covered = agreement_seconds(
        [Span(0.0, 5.0, SPEECH, 0.9)], [Span(0.0, 5.0, MUSIC, 0.9)]
    )
    assert agreed == 0.0
    assert covered == pytest.approx(5.0)


def test_comparing_against_an_empty_timeline_covers_nothing() -> None:
    assert agreement_seconds([Span(0.0, 5.0, SPEECH, 0.9)], []) == (0.0, 0.0)


def test_an_overlay_of_many_regions_matches_a_plain_scan() -> None:
    """The two-pointer walk must agree with the obvious quadratic version."""
    base = [Span(float(i), float(i + 1), MUSIC if i % 2 else OTHER, 0.9) for i in range(60)]
    regions = [(float(3 * i) + 0.25, float(3 * i) + 1.75, None) for i in range(20)]
    fast = overlay_regions(base, regions, SPEECH)
    slow = _overlay_by_scanning(base, regions, SPEECH)
    assert shape(fast) == shape(slow)


def _overlay_by_scanning(
    base: list[Span], regions: list[tuple[float, float, float | None]], label: str
) -> list[Span]:
    """The straightforward version, for the test above to compare against."""
    out: list[Span] = []
    for span in base:
        cursor = span.start_s
        for r_start, r_end, _score in sorted(regions):
            if r_end <= cursor or r_start >= span.end_s:
                continue
            if r_start > cursor:
                out.append(Span(cursor, r_start, span.label, span.confidence, span.detail))
            cursor = min(span.end_s, r_end)
        if cursor < span.end_s:
            out.append(Span(cursor, span.end_s, span.label, span.confidence, span.detail))
    for r_start, r_end, score in sorted(regions):
        out.append(Span(r_start, r_end, label, score, None))
    out.sort(key=lambda s: (s.start_s, s.end_s))
    merged: list[Span] = []
    for span in out:
        if merged and merged[-1].label == span.label and merged[-1].end_s >= span.start_s:
            prev = merged[-1]
            merged[-1] = Span(
                prev.start_s, max(prev.end_s, span.end_s), prev.label, prev.confidence, prev.detail
            )
        else:
            merged.append(span)
    return merged
