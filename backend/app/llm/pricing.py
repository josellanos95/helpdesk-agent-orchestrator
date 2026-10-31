from decimal import Decimal

from app.llm.base import Usage

# USD per 1M tokens: (input, output).
# Checked against OpenAI's own pricing page (developers.openai.com/api/docs/pricing) on 2026-10-31.
# Cached-input discounts are ignored, so a cost shown can only be higher than the bill, never lower.
# Unknown models cost 0 and are flagged by `is_priced`.
PRICES_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-5-mini": (Decimal("0.25"), Decimal("2.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
}


def _price_for(model: str) -> tuple[Decimal, Decimal] | None:
    # The API echoes dated snapshots ("gpt-5-mini-2025-08-07"): match the longest known prefix.
    for known in sorted(PRICES_PER_MILLION, key=len, reverse=True):
        if model == known or model.startswith(known + "-"):
            return PRICES_PER_MILLION[known]
    return None


def is_priced(model: str) -> bool:
    return _price_for(model) is not None


def cost_usd(model: str, usage: Usage) -> Decimal:
    price = _price_for(model)
    if price is None:
        return Decimal(0)
    per_in, per_out = price
    return (per_in * usage.prompt_tokens + per_out * usage.completion_tokens) / Decimal(1_000_000)


# USD per 1M input tokens for embedding models (same page, same date).
EMBEDDING_PRICES_PER_MILLION: dict[str, Decimal] = {
    "text-embedding-3-small": Decimal("0.02"),
    "text-embedding-3-large": Decimal("0.13"),
}
CHARS_PER_TOKEN = 4  # rough rule of thumb for English; embeddings are cheap enough that this is fine


def embedding_cost_usd(model: str, text: str) -> Decimal:
    """Estimated cost of embedding `text`. Unknown models (hashing, other providers) cost 0."""
    price = EMBEDDING_PRICES_PER_MILLION.get(model)
    if price is None:
        return Decimal(0)
    return price * Decimal(max(1, len(text) // CHARS_PER_TOKEN)) / Decimal(1_000_000)
