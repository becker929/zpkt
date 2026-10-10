"""Embedding-based nearest-neighbour retrieval for RAG context.

retrieve() finds the top-k most similar corpus entries to a query embedding
and formats them into a prompt snippet for the taste judge.
"""

from __future__ import annotations

import json

from taste.corpus.models import AnnotationEntry


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Returns 0.0 for zero vectors."""
    import numpy as np
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    return float(np.dot(va, vb) / (na * nb)) if na > 0 and nb > 0 else 0.0


def retrieve(
    query_embedding: list[float],
    corpus: list[AnnotationEntry],
    top_k: int = 5,
) -> list[AnnotationEntry]:
    """Return the top-k corpus entries most similar to query_embedding."""
    if not query_embedding or not corpus:
        return []

    scored: list[tuple[float, AnnotationEntry]] = []
    for entry in corpus:
        try:
            profile = json.loads(entry.profile_json)
            emb = profile.get("embedding")
            if emb and len(emb) == len(query_embedding):
                score = cosine(query_embedding, emb)
                scored.append((score, entry))
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda t: t[0], reverse=True)
    return [e for _, e in scored[:top_k]]


def format_context(entries: list[AnnotationEntry]) -> str:
    """Format retrieved entries as a prompt block for the taste judge."""
    if not entries:
        return "No similar entries found in corpus."
    lines = ["Retrieved context from corpus:\n"]
    for i, e in enumerate(entries, start=1):
        lines.append(
            f"[{i}] clip_id={e.clip_id}  score={e.score}/5\n"
            f"    feedback: {e.human_feedback or '(none)'}\n"
            f"    verdict: {e.verdict_json[:120]}..."
        )
    return "\n".join(lines)
