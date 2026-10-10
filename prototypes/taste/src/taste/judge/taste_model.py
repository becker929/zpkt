"""RAG-based taste judge.

The "taste model" is not a neural network.  It is a retrieval-augmented
generation pipeline:
  1. Retrieve top-k most similar corpus entries by embedding cosine similarity
  2. Format retrieved entries + the new AudioProfile as a structured prompt
  3. Call an LLM (Claude) for a structured Verdict: score 1-5, rationale, suggestions

No direct imports from ears or hands — AudioProfile arrives as a JSON string.
"""

from __future__ import annotations

import json
import uuid

from taste.models import Verdict
from taste.corpus.models import AnnotationEntry
from taste.corpus.retrieval import retrieve, format_context


class TasteModel:
    """RAG taste judge.

    Args:
        corpus: list of AnnotationEntry used as retrieval context.
        llm_client: optional LLM client; if None, returns a stub verdict.
        top_k: number of corpus entries to retrieve per judgment.
    """

    def __init__(
        self,
        corpus: list[AnnotationEntry] | None = None,
        llm_client: object | None = None,
        top_k: int = 5,
    ) -> None:
        self._corpus = corpus or []
        self._llm = llm_client
        self._top_k = top_k

    def judge(self, profile_json: str) -> Verdict:
        """Score a render from its AudioProfile JSON."""
        try:
            profile = json.loads(profile_json)
            clip_id = profile.get("clip_id", str(uuid.uuid4()))
            embedding = profile.get("embedding")
        except json.JSONDecodeError as exc:
            return Verdict(
                clip_id="unknown",
                score=1,
                rationale=f"Invalid profile JSON: {exc}",
            )

        context_entries = retrieve(embedding or [], self._corpus, self._top_k)
        context_text = format_context(context_entries)

        if self._llm is None:
            return Verdict(
                clip_id=clip_id,
                score=3,
                rationale="[stub] LLM client not configured.",
                retrieved_ids=[e.clip_id for e in context_entries],
                model="stub",
            )

        prompt = self._build_prompt(profile, context_text)
        raw = self._call_llm(prompt)
        return self._parse_verdict(clip_id, raw, context_entries)

    def _build_prompt(self, profile: dict, context: str) -> str:
        return (
            "You are a taste judge for electronic music production.\n\n"
            f"{context}\n\n"
            f"New render to evaluate:\n{json.dumps(profile, indent=2)}\n\n"
            "Return JSON with keys: score (1-5), rationale (str), suggestions (list[str])."
        )

    def _call_llm(self, prompt: str) -> str:
        raise NotImplementedError("Wire up an LLM client in subclass or inject one.")

    @staticmethod
    def _strip_markdown(raw: str) -> str:
        """Strip markdown code fences that LLMs sometimes wrap JSON in."""
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # drop opening fence (```json or ```)
            lines = lines[1:]
            # drop closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        return stripped

    def _parse_verdict(
        self, clip_id: str, raw: str, context: list[AnnotationEntry]
    ) -> Verdict:
        try:
            data = json.loads(self._strip_markdown(raw))
            return Verdict(
                clip_id=clip_id,
                score=int(data["score"]),
                rationale=str(data.get("rationale", "")),
                suggestions=list(data.get("suggestions", [])),
                retrieved_ids=[e.clip_id for e in context],
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            return Verdict(
                clip_id=clip_id,
                score=1,
                rationale=f"Failed to parse LLM response: {exc}\nRaw: {raw[:200]}",
                retrieved_ids=[e.clip_id for e in context],
            )
