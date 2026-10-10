"""
Cosine-similarity retrieval over the corpus.
Biases toward corrections (2x weight) and extreme verdicts (1s and 5s, 1.5x weight).
Filters by decomposition level to ensure contextual consistency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import numpy as np

from .models import AnnotationEntry
from .store import CorpusStore


@dataclass
class RetrievedEntry:
    entry: AnnotationEntry
    similarity: float
    weight: float


def retrieve(
    query_embedding: list[float],
    store: CorpusStore,
    top_k: int = 15,
    decomposition: Optional[str] = None,
) -> list[RetrievedEntry]:
    """
    Retrieve the top-k most relevant corpus entries for a query embedding.

    Scoring:
        score = cosine_similarity * weight_multiplier
    where weight_multiplier is:
        - 2.0 for corrections (source_tag == "correction")
        - 1.5 for extreme verdicts (1 or 5)
        - 1.0 otherwise

    If decomposition is provided, only entries matching that decomposition are returned.
    Falls back to all entries if the filtered set is too small.
    """
    if not query_embedding:
        return []

    all_entries = store.get_all_annotations()
    if not all_entries:
        return []

    # Filter by decomposition
    if decomposition:
        filtered = [e for e in all_entries if e.decomposition == decomposition]
        if len(filtered) >= max(3, top_k // 2):
            all_entries = filtered

    # Build matrix of embeddings for entries that have them
    valid = [(e, e.embedding) for e in all_entries if len(e.embedding) == 512]
    if not valid:
        # Fall back to returning highest-verdict entries without similarity
        sorted_entries = sorted(all_entries, key=lambda e: e.verdict, reverse=True)
        return [
            RetrievedEntry(entry=e, similarity=0.0, weight=_weight(e))
            for e in sorted_entries[:top_k]
        ]

    entries, embeddings = zip(*valid)
    matrix = np.array(embeddings, dtype=np.float32)  # (N, 512)
    query = np.array(query_embedding, dtype=np.float32)  # (512,)

    # L2-normalize
    query_norm = query / (np.linalg.norm(query) + 1e-10)
    row_norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_norm = matrix / row_norms

    # Cosine similarities
    similarities = matrix_norm @ query_norm  # (N,)

    # Weight multipliers
    weights = np.array([_weight(e) for e in entries], dtype=np.float32)
    scores = similarities * weights

    # Top-k by weighted score
    top_idx = np.argsort(scores)[::-1][:top_k]

    return [
        RetrievedEntry(
            entry=entries[i],
            similarity=float(similarities[i]),
            weight=float(weights[i]),
        )
        for i in top_idx
    ]


def _weight(entry: AnnotationEntry) -> float:
    w = 1.0
    if entry.source_tag == "correction":
        w *= 2.0
    if entry.verdict in (1, 5):
        w *= 1.5
    return w


def format_retrieved_for_prompt(retrieved: list[RetrievedEntry]) -> str:
    """Format retrieved entries as a prompt section."""
    if not retrieved:
        return "No relevant corpus entries found."
    lines = []
    for i, r in enumerate(retrieved, 1):
        e = r.entry
        lines.append(
            f"[{i}] clip_id={e.clip_id} | source={e.source_track} | "
            f"verdict={e.verdict}/5 | lens={e.evaluation_lens} | "
            f"decomposition={e.decomposition} | similarity={r.similarity:.3f}"
        )
        if e.what_works:
            lines.append(f"    WORKS: {e.what_works}")
        if e.what_fails:
            lines.append(f"    FAILS: {e.what_fails}")
        if e.comparison_anchors:
            lines.append(f"    ANCHORS: {e.comparison_anchors}")
        if e.notes:
            lines.append(f"    NOTES: {e.notes}")
    return "\n".join(lines)
