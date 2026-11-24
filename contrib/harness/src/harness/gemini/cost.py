"""What Gemini costs, estimated: each turn's tokens at the standard rates, and the month's total with the image wall's
images. The real bill is on the AI Studio and Cloud Billing pages; the key cannot read billing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# Dollars per million tokens (input, output incl. thinking), the standard tier, for the estimate only, by family:
# flash-lite, flash, 2.5 pro, and everything else at the 3.x pro rate (so an unknown model errs high). Cached input
# is billed at a tenth.
PRICES = (("flash-lite", 0.1, 0.4), ("flash", 0.5, 3.0), ("2.5-pro", 1.25, 10.0))
IMAGE_OUT = 120.0  # dollars per million image-output tokens (1120 a 1K/2K image: about $0.134)


def price(model: str) -> tuple[float, float]:
    for part, i, o in PRICES:
        if part in model and "image" not in model:
            return i, o
    return 2.0, 12.0


def cost(model: str, usage: dict) -> float:
    """An estimate of one generateContent call's dollars from its usageMetadata (images included)."""
    i, o = price(model)
    image = sum(
        d.get("tokenCount", 0) for d in usage.get("candidatesTokensDetails") or [] if d.get("modality") == "IMAGE"
    )
    text_out = usage.get("candidatesTokenCount", 0) - image + usage.get("thoughtsTokenCount", 0)
    return (usage.get("promptTokenCount", 0) * i + text_out * o + image * IMAGE_OUT) / 1e6


def turn_cost(model: str, usage: dict) -> float:
    """An estimate of one ACP turn's dollars from session/prompt's usage."""
    i, o = price(model)
    cached = usage.get("cachedReadTokens", 0)
    fresh = max(0, usage.get("inputTokens", 0) - cached)
    out = usage.get("outputTokens", 0) + usage.get("thoughtTokens", 0)
    return (fresh * i + cached * i * 0.1 + out * o) / 1e6


def image_cost(rec: dict) -> float:
    t = rec.get("tokens") or {}
    if "candidatesTokensDetails" in t:
        return cost(rec.get("model", ""), t)
    return 0.134 if "pro" in rec.get("model", "") else 0.07  # imported records only kept a total


def month_usage(usage_rows: list[dict], images_manifest: Path, month: str | None = None) -> dict:
    """This month's estimated dollars: Gemini CLI's turns here, and every image the image wall made (its images.jsonl)."""
    month = month or datetime.now(UTC).strftime("%Y-%m")
    agent = sum(r.get("dollars", 0.0) for r in usage_rows if r.get("at", "").startswith(month))
    img, n = 0.0, 0
    if images_manifest.is_file():
        for line in images_manifest.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("created", "").startswith(month):
                img += image_cost(r)
                n += 1
    return {"month": month, "agent": round(agent, 4), "images": round(img, 4), "image_count": n}
