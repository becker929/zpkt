"""Smoke tests for the taste package.

All tests run offline with in-memory SQLite and stub LLM — no API keys required.
"""

from __future__ import annotations

import json

from taste.models import FeedbackTuple, Verdict
from taste.corpus.models import AnnotationEntry, EvaluationLens
from taste.corpus.store import CorpusStore
from taste.corpus.retrieval import retrieve, format_context, cosine
from taste.judge.taste_model import TasteModel


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_verdict_round_trip() -> None:
    v = Verdict(
        clip_id="abc",
        score=4,
        rationale="Good punch, lacks warmth.",
        suggestions=["boost 80 Hz", "reduce 8 kHz"],
    )
    restored = Verdict.model_validate_json(v.model_dump_json())
    assert restored == v


def test_feedback_tuple_round_trip() -> None:
    v = Verdict(clip_id="x", score=3, rationale="OK")
    ft = FeedbackTuple(
        session_id="s1",
        render_path="/tmp/r.mp3",
        profile_json='{"clip_id":"x"}',
        verdict=v,
        human_feedback="Needs more bass",
    )
    restored = FeedbackTuple.model_validate_json(ft.model_dump_json())
    assert restored.session_id == "s1"


# ---------------------------------------------------------------------------
# Corpus store
# ---------------------------------------------------------------------------

def test_corpus_store_add_get() -> None:
    store = CorpusStore()
    entry = AnnotationEntry(
        clip_id="c1",
        render_path="/tmp/r.mp3",
        profile_json='{"clip_id":"c1","embedding":[1.0,0.0]}',
        verdict_json='{"score":4}',
        score=4,
    )
    store.add(entry)
    assert store.count() == 1
    retrieved = store.get("c1")
    assert retrieved is not None
    assert retrieved.score == 4


def test_corpus_store_upsert() -> None:
    store = CorpusStore()
    entry = AnnotationEntry(
        clip_id="c1",
        render_path="/r.mp3",
        profile_json="{}",
        verdict_json="{}",
        score=3,
    )
    store.add(entry)
    updated = entry.model_copy(update={"score": 5})
    store.add(updated)
    assert store.count() == 1
    assert store.get("c1").score == 5  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def test_cosine_identical() -> None:
    v = [1.0, 0.0, 0.0]
    assert abs(cosine(v, v) - 1.0) < 1e-6


def test_retrieve_empty_corpus() -> None:
    result = retrieve([1.0, 0.0], [], top_k=5)
    assert result == []


def test_retrieve_top_k() -> None:
    def _entry(cid: str, emb: list[float], score: int) -> AnnotationEntry:
        return AnnotationEntry(
            clip_id=cid,
            render_path=f"/{cid}.mp3",
            profile_json=json.dumps({"clip_id": cid, "embedding": emb}),
            verdict_json="{}",
            score=score,
        )

    corpus = [
        _entry("similar", [1.0, 0.0], 5),
        _entry("orthogonal", [0.0, 1.0], 2),
        _entry("opposite", [-1.0, 0.0], 1),
    ]
    result = retrieve([1.0, 0.0], corpus, top_k=2)
    assert len(result) == 2
    assert result[0].clip_id == "similar"


def test_format_context_empty() -> None:
    text = format_context([])
    assert "No similar" in text


# ---------------------------------------------------------------------------
# Taste model (stub)
# ---------------------------------------------------------------------------

def test_taste_model_stub_verdict() -> None:
    model = TasteModel()
    profile_json = json.dumps({
        "clip_id": "test-clip",
        "source_path": "/tmp/test.mp3",
        "embedding": [0.1] * 512,
    })
    verdict = model.judge(profile_json)
    assert verdict.clip_id == "test-clip"
    assert 1 <= verdict.score <= 5
    assert verdict.model == "stub"


def test_taste_model_invalid_json() -> None:
    model = TasteModel()
    verdict = model.judge("not valid json {")
    assert verdict.clip_id == "unknown"
    assert verdict.score == 1
    assert "Invalid" in verdict.rationale
