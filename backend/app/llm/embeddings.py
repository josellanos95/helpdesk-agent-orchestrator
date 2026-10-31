"""Turning text into vectors.

`OpenAIEmbedder` is the real thing. `HashingEmbedder` is a deterministic stand-in (feature hashing of
words): no network, no cost, similar texts get similar vectors. It is good enough to develop and test
retrieval end to end offline; it is NOT a semantic model, so quality numbers must come from the real one.
"""

import hashlib
import math
import re
from typing import Protocol

import httpx
from openai import AsyncOpenAI

from app.db.models import EMBEDDING_DIMENSIONS

BATCH_SIZE = 96
MAX_INPUT_CHARS = 8000  # the API limit is in tokens; this keeps a single oversized text from failing a batch
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 1


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = [t[:MAX_INPUT_CHARS] or " " for t in texts[start : start + BATCH_SIZE]]
            kwargs: dict = {"model": self.model, "input": batch}
            if self.model.startswith("text-embedding-3"):
                kwargs["dimensions"] = self.dimensions  # only the 3-series accepts it
            response = await self._client.embeddings.create(**kwargs)
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise EmbeddingError(f"asked for {len(batch)} embeddings, got {len(ordered)}")
            for item in ordered:
                if len(item.embedding) != self.dimensions:
                    raise EmbeddingError(
                        f"{self.model} returned {len(item.embedding)} dimensions, expected {self.dimensions}"
                    )
                vectors.append(list(item.embedding))
        return vectors


_WORD = re.compile(r"[a-z0-9]+")
_SUFFIXES = ("ing", "ed", "es", "s")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


class HashingEmbedder:
    model = "hashing-v1"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        words = [_stem(w) for w in _WORD.findall(text.lower())]
        for token in [*words, *(f"{a}_{b}" for a, b in zip(words, words[1:], strict=False))]:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:6], "big") % self.dimensions
            vector[index] += 1.0 if digest[6] % 2 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:  # empty text: a fixed unit vector keeps cosine distance finite
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


def build_embedder(settings) -> Embedder | None:
    """The embedder the settings ask for, or None when it cannot be built (no API key)."""
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    api_key = settings.embedding_api_key or settings.openai_api_key
    if not api_key:
        return None
    return OpenAIEmbedder(
        api_key=api_key,
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
    )
