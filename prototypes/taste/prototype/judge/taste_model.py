"""
RAG Taste Model (Scaling Taste §4).
Retrieves relevant corpus entries and asks Claude to judge new audio
as if it were the producer whose taste is documented in the corpus.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from ..corpus.models import AnnotationEntry
from ..corpus.store import CorpusStore
from ..corpus.retrieval import retrieve, format_retrieved_for_prompt, RetrievedEntry


@dataclass
class Verdict:
    score: int                              # 1–5
    confidence: float                       # 0–1
    rationale: str
    suggestions: list[str] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    low_confidence_reason: Optional[str] = None
    elapsed_seconds: float = 0.0


class TasteModel:
    def __init__(self, store: CorpusStore, anthropic_client=None, top_k: int = 15):
        self._store = store
        self._client = anthropic_client
        self._top_k = top_k

    def _get_client(self):
        if self._client:
            return self._client
        import anthropic, json, os
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "llm.config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            return anthropic.Anthropic(api_key=cfg["claude_api_key"])
        except Exception:
            return anthropic.Anthropic()

    def judge(self, profile: "AudioProfile", decomposition: str = "full_mix") -> Verdict:  # type: ignore
        """
        Judge a new audio clip against the corpus.

        Steps:
        1. Retrieve top-k corpus entries by DCLAP embedding similarity
        2. Assess confidence (score variance and similarity spread)
        3. Build prompt and call LLM
        4. Parse structured response
        """
        t0 = time.time()

        retrieved = retrieve(
            query_embedding=profile.embedding,
            store=self._store,
            top_k=self._top_k,
            decomposition=decomposition,
        )

        confidence, low_conf_reason = _assess_confidence(retrieved, profile)
        corpus_section = format_retrieved_for_prompt(retrieved)

        # Build description from profile
        description = profile.description if profile.description else _fallback_description(profile)

        prompt = _JUDGE_PROMPT.format(
            corpus_section=corpus_section,
            description=description,
        )

        client = self._get_client()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        verdict = _parse_response(raw)
        verdict.confidence = confidence
        verdict.low_confidence_reason = low_conf_reason
        verdict.retrieved_ids = [r.entry.clip_id for r in retrieved]
        verdict.elapsed_seconds = time.time() - t0

        return verdict

    def correct(
        self,
        original_entry: AnnotationEntry,
        corrected_verdict: int,
        correction_notes: str,
    ) -> AnnotationEntry:
        """
        Add a correction entry to the corpus when the producer disagrees with the model.
        """
        from ..corpus.models import AnnotationEntry, SourceTag
        correction = AnnotationEntry(
            clip_id=original_entry.clip_id,
            source_track=original_entry.source_track,
            time_range=original_entry.time_range,
            decomposition=original_entry.decomposition,
            evaluation_lens=original_entry.evaluation_lens,
            verdict=corrected_verdict,
            notes=correction_notes,
            embedding=original_entry.embedding,
            source_tag=SourceTag.correction,
            corrects=original_entry.clip_id,
        )
        self._store.add_annotation(correction)
        return correction

    def eval_validation_set(
        self, validation_entries: list[AnnotationEntry]
    ) -> dict:
        """
        Run the taste model on held-out entries and report agreement metrics.
        Requires entries to have an associated AudioProfile in the cache.
        """
        results = []
        for entry in validation_entries:
            cached = self._store.get_cached_profile(entry.clip_id)
            if not cached:
                continue
            import dataclasses, json
            from ..audio.analyzer import AudioProfile

            profile_data = json.loads(cached)
            # Reconstruct minimal AudioProfile for judgment
            profile = _minimal_profile_from_dict(profile_data)
            try:
                verdict = self.judge(profile)
                score_diff = abs(verdict.score - entry.verdict)
                results.append({
                    "clip_id": entry.clip_id,
                    "expected": entry.verdict,
                    "predicted": verdict.score,
                    "score_diff": score_diff,
                    "within_1": score_diff <= 1,
                    "confidence": verdict.confidence,
                })
            except Exception as e:
                results.append({"clip_id": entry.clip_id, "error": str(e)})

        if not results:
            return {"error": "no cached profiles found for validation entries"}

        valid = [r for r in results if "error" not in r]
        agreement = sum(1 for r in valid if r["within_1"]) / len(valid) if valid else 0.0
        return {
            "total": len(results),
            "evaluated": len(valid),
            "agreement_within_1": agreement,
            "mean_score_diff": (
                sum(r["score_diff"] for r in valid) / len(valid) if valid else None
            ),
            "results": results,
        }


_JUDGE_PROMPT = """You are evaluating a music clip on behalf of a producer whose taste
preferences are documented in the corpus below. The producer makes hard techno and industrial music.

PRODUCER'S DOCUMENTED TASTE (ranked by relevance):
{corpus_section}

NEW CLIP DESCRIPTION:
{description}

Based strictly on the producer's documented preferences — citing specific corpus entries by their clip_id —
provide your evaluation in this exact JSON format:

{{
  "score": <integer 1-5>,
  "rationale": "<2-4 sentences citing corpus entries. Every claim must reference a specific clip_id.>",
  "suggestions": ["<actionable change 1>", "<actionable change 2>", "<actionable change 3>"]
}}

Score guide: 1=delete immediately, 2=missing something critical, 3=functional but no excitement,
4=good, minor issues, 5=would play out / reference-worthy.

JSON only, no preamble:"""


def _parse_response(raw: str) -> Verdict:
    try:
        # Extract JSON even if surrounded by prose
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return Verdict(
                score=max(1, min(5, int(data.get("score", 3)))),
                confidence=0.0,
                rationale=str(data.get("rationale", "")),
                suggestions=list(data.get("suggestions", [])),
            )
    except Exception:
        pass
    return Verdict(score=3, confidence=0.0, rationale=raw[:500], suggestions=[])


def _assess_confidence(retrieved: list[RetrievedEntry], profile) -> tuple[float, Optional[str]]:
    if not retrieved:
        return 0.1, "no corpus entries available"

    similarities = [r.similarity for r in retrieved[:5]]
    verdicts = [r.entry.verdict for r in retrieved[:10]]

    mean_sim = sum(similarities) / len(similarities) if similarities else 0.0

    import statistics
    verdict_std = statistics.stdev(verdicts) if len(verdicts) > 1 else 0.0

    # Low confidence triggers
    if mean_sim < 0.5:
        return 0.3, f"low retrieval similarity (mean={mean_sim:.2f}) — novel material"
    if verdict_std > 1.5:
        return 0.5, f"contradictory evidence (verdict std={verdict_std:.2f})"
    if not profile.embedding:
        return 0.4, "no embedding available for query"

    # High confidence
    if mean_sim > 0.8 and verdict_std < 0.8:
        return 0.9, None

    # Scale linearly
    confidence = min(1.0, mean_sim * 0.8 + (1.0 - min(1.0, verdict_std / 2.0)) * 0.2)
    return float(confidence), None


def _minimal_profile_from_dict(data: dict):
    """Reconstruct a minimal AudioProfile from cached JSON dict."""
    from ..audio.analyzer import AudioProfile
    profile = AudioProfile()
    profile.clip_id = data.get("clip_id", "")
    profile.audio_path = data.get("audio_path", "")
    profile.duration_seconds = data.get("duration_seconds", 0.0)
    profile.description = data.get("description", "")
    profile.embedding = data.get("embedding", [])
    return profile
