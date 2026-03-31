"""
Audio describers — convert an AudioProfile (and optionally the raw waveform)
into a production-vocabulary natural-language description.

Phase 1 — LLMDescriber
    Narrates the *structured* AudioProfile features via Claude Haiku.
    No audio required at inference time.

Phase 2 — GeminiDescriber
    Uploads the raw audio to Gemini 2.5 Flash and asks it to describe
    the sonic character directly from the waveform. The structured features
    are appended as grounding context.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Protocol


class Describer(Protocol):
    def describe(self, profile: "AudioProfile") -> str:  # type: ignore[name-defined]
        ...


class LLMDescriber:
    """Phase 1: text LLM narrates structured AudioProfile features."""

    def __init__(self, anthropic_client=None):
        self._client = anthropic_client

    def _get_client(self):
        if self._client:
            return self._client
        import anthropic
        import json, os
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "llm.config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            return anthropic.Anthropic(api_key=cfg["claude_api_key"])
        except Exception:
            return anthropic.Anthropic()

    def describe(self, profile: "AudioProfile") -> str:  # type: ignore[name-defined]
        summary = _build_feature_summary(profile)
        if not summary.strip():
            return ""

        prompt = _DESCRIBE_PROMPT.format(feature_summary=summary)
        client = self._get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


_DESCRIBE_PROMPT = """You are describing an audio clip to a music producer for purposes of taste evaluation.
Using ONLY the measured features below, write a concise (3–6 sentence) description of the sonic character.
Use production vocabulary. Do NOT give opinions or scores — only describe what you observe.
Focus on: spectral texture, energy distribution, rhythmic feel, tonal content, and spatial character.

Measured features:
{feature_summary}

Description:"""


def _build_feature_summary(profile: "AudioProfile") -> str:  # type: ignore[name-defined]
    lines = []
    lines.append(f"Duration: {profile.duration_seconds:.1f}s")

    r = profile.rhythm
    if r:
        if r.bpm:
            lines.append(f"Tempo: {r.bpm:.1f} BPM")
        if r.meter_numerator:
            lines.append(f"Meter: {r.meter_numerator}/4")
        if r.swing_ratio is not None:
            swing_desc = "straight" if r.swing_ratio < 0.54 else "swung"
            lines.append(f"Groove: {swing_desc} (swing ratio {r.swing_ratio:.2f})")
        if r.groove_density:
            lines.append(f"Rhythmic density: {r.groove_density:.1f} onsets/beat")
        if r.beat_regularity:
            reg = "very tight" if r.beat_regularity < 0.01 else (
                "tight" if r.beat_regularity < 0.03 else "loose"
            )
            lines.append(f"Beat regularity: {reg} (IBI std {r.beat_regularity:.3f}s)")

    lo = profile.loudness
    if lo:
        if lo.lufs_integrated is not None:
            lines.append(f"Integrated loudness: {lo.lufs_integrated:.1f} LUFS")
        if lo.lufs_short_term_peak is not None:
            lines.append(f"Short-term peak: {lo.lufs_short_term_peak:.1f} LUFS")
        if lo.camelot_key:
            lines.append(f"Key: {lo.camelot_key}")
        if lo.band_energy:
            be = lo.band_energy
            dominant = max(be, key=be.get)
            lines.append(
                f"Spectral balance: sub={be.get('sub',0):.1%}, "
                f"low={be.get('low',0):.1%}, mid={be.get('mid',0):.1%}, "
                f"high={be.get('high',0):.1%}, air={be.get('air',0):.1%} "
                f"(dominant: {dominant})"
            )

    sp = profile.spectral
    if sp:
        lines.append(f"Spectral centroid: {sp.spectral_centroid_mean:.0f} Hz "
                     f"(±{sp.spectral_centroid_std:.0f})")
        if sp.spectral_flatness_mean is not None:
            flat_desc = "noisy/tonal" if sp.spectral_flatness_mean < 0.01 else (
                "moderately tonal" if sp.spectral_flatness_mean < 0.1 else "noise-like"
            )
            lines.append(f"Spectral texture: {flat_desc} "
                         f"(flatness {sp.spectral_flatness_mean:.3f})")
        if sp.harmonic_ratio_mean is not None:
            lines.append(f"Harmonic ratio: {sp.harmonic_ratio_mean:.2f}")
        if sp.key:
            lines.append(f"Estimated key (essentia): {sp.key} "
                         f"(strength {sp.key_strength:.2f})")
        if sp.danceability is not None:
            lines.append(f"Danceability: {sp.danceability:.2f}")

    pi = profile.pitch
    if pi and pi.note_count > 0:
        lines.append(f"Note count: {pi.note_count} ({pi.note_density:.1f} notes/sec)")
        if pi.pitch_min_midi and pi.pitch_max_midi:
            lines.append(f"Pitch range: MIDI {pi.pitch_min_midi}–{pi.pitch_max_midi} "
                         f"({pi.pitch_range_semitones} semitones)")
        if pi.dominant_pitch_class:
            lines.append(f"Dominant pitch class: {pi.dominant_pitch_class}")
        if pi.polyphony_mean:
            lines.append(f"Mean polyphony: {pi.polyphony_mean:.1f} simultaneous notes")

    return "\n".join(lines)


class GeminiDescriber:
    """Phase 2: Gemini 2.5 Flash hears the raw audio and describes it.

    The structured AudioProfile features are included as grounding context so
    the model can anchor its prose to measured values (BPM, LUFS, key, etc.).
    Falls back to LLMDescriber if the audio file is missing or the API call fails.
    """

    _MIME_MAP = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
    }

    def __init__(self, gemini_client=None, model: str = "gemini-2.5-flash"):
        self._client = gemini_client
        self._model = model

    def _get_client(self):
        if self._client:
            return self._client
        import google.generativeai as genai
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "llm.config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            genai.configure(api_key=cfg["gemini_api_key"])
        except Exception:
            pass
        return genai

    def describe(self, profile: "AudioProfile") -> str:  # type: ignore[name-defined]
        audio_path = getattr(profile, "audio_path", None)

        if not audio_path or not os.path.exists(audio_path):
            return LLMDescriber().describe(profile)

        suffix = os.path.splitext(audio_path)[1].lower()
        mime_type = self._MIME_MAP.get(suffix, "audio/mpeg")

        feature_summary = _build_feature_summary(profile)

        try:
            genai = self._get_client()
            model = genai.GenerativeModel(self._model)
            audio_file = genai.upload_file(path=audio_path, mime_type=mime_type)
            prompt = _GEMINI_PROMPT.format(feature_summary=feature_summary)
            response = model.generate_content([audio_file, prompt])
            return response.text.strip()
        except Exception as exc:
            # Graceful fallback — never crash the analysis pipeline
            fallback = LLMDescriber().describe(profile)
            return f"{fallback}\n[Gemini fallback: {exc}]" if not fallback else fallback


_GEMINI_PROMPT = """You are describing this audio clip to a music producer for purposes of taste evaluation.
Listen carefully to the sonic character of the clip, then write a concise (3–6 sentence) description.
Use production vocabulary. Do NOT give opinions or scores — only describe what you observe.
Focus on: spectral texture, energy distribution, rhythmic feel, tonal content, transient character, and spatial quality.

The following measurements were extracted automatically and should anchor your description:
{feature_summary}

Description:"""


# ── Convenience functions ─────────────────────────────────────────────────────

def describe(profile: "AudioProfile") -> str:  # type: ignore[name-defined]
    """Describe using the default Phase 1 (text-LLM) describer."""
    return LLMDescriber().describe(profile)


def describe_gemini(profile: "AudioProfile") -> str:  # type: ignore[name-defined]
    """Describe using the Phase 2 Gemini audio describer."""
    return GeminiDescriber().describe(profile)
