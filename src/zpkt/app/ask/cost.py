"""What a Gemini turn costs, estimated from its tokens at the standard rates (the real bill is on Google's billing
page; the key cannot read it). The rates are the same as the harness's studio Gemini page uses."""

from __future__ import annotations

from typing import Any

# Dollars per million tokens (input, output including thinking), by model family. An unknown model errs high.
PRICES = (("flash-lite", 0.1, 0.4), ("flash", 0.5, 3.0), ("2.5-pro", 1.25, 10.0))
UNKNOWN = (2.0, 12.0)
CACHED_RATE = 0.1  # cached input is billed at a tenth


def price(model: str) -> tuple[float, float]:
    for part, i, o in PRICES:
        if part in model and "image" not in model:
            return i, o
    return UNKNOWN


def turn_cost(model: str, usage: dict[str, Any]) -> float:
    """Dollars for one ACP turn, from the `usage` of session/prompt's answer."""
    i, o = price(model)
    cached = usage.get("cachedReadTokens", 0)
    fresh = max(0, usage.get("inputTokens", 0) - cached)
    out = usage.get("outputTokens", 0) + usage.get("thoughtTokens", 0)
    return (fresh * i + cached * i * CACHED_RATE + out * o) / 1e6
