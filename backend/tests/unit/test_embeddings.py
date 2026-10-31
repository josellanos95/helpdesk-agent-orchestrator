import json
import math

import httpx
import pytest

from app.config import Settings
from app.db.models import EMBEDDING_DIMENSIONS
from app.llm.embeddings import (
    BATCH_SIZE,
    EmbeddingError,
    HashingEmbedder,
    OpenAIEmbedder,
    build_embedder,
)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # vectors are unit length


# ------------------------------------------------------------------------ hashing stand-in


async def test_hashing_vectors_have_the_right_size_and_unit_length():
    [vec] = await HashingEmbedder().embed(["VPN keeps disconnecting every ten minutes"])
    assert len(vec) == EMBEDDING_DIMENSIONS
    assert math.isclose(sum(v * v for v in vec), 1.0, rel_tol=1e-9)


async def test_hashing_is_deterministic():
    a, b = await HashingEmbedder().embed(["same text", "same text"])
    assert a == b


async def test_texts_about_the_same_thing_are_closer_than_unrelated_ones():
    base, near, far = await HashingEmbedder().embed(
        [
            "VPN keeps disconnecting on my laptop",
            "my laptop VPN disconnects all the time",
            "quarterly payroll report formatting",
        ]
    )
    assert cosine(base, near) > 0.3
    assert cosine(base, far) < 0.1  # unrelated text shares almost nothing


async def test_empty_text_gives_a_usable_vector_not_nan():
    [vec] = await HashingEmbedder().embed([""])
    assert not any(math.isnan(v) for v in vec) and math.isclose(sum(v * v for v in vec), 1.0)


# ---------------------------------------------------------------------- the OpenAI client


def response(vectors: list[list[float]], *, shuffled: bool = False) -> dict:
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]
    if shuffled:
        data.reverse()  # the API does not promise order; the client must use `index`
    return {
        "object": "list",
        "data": data,
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


def make(handler, **kwargs) -> OpenAIEmbedder:
    return OpenAIEmbedder(
        api_key="sk-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def vector(seed: int) -> list[float]:
    return [float(seed)] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


async def test_results_are_returned_in_input_order_even_if_the_api_shuffles_them():
    def handler(request):
        n = len(json.loads(request.content)["input"])
        return httpx.Response(200, json=response([vector(i) for i in range(n)], shuffled=True))

    vectors = await make(handler).embed(["a", "b", "c"])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]


async def test_large_inputs_are_sent_in_batches():
    sizes: list[int] = []

    def handler(request):
        n = len(json.loads(request.content)["input"])
        sizes.append(n)
        return httpx.Response(200, json=response([vector(0)] * n))

    vectors = await make(handler).embed([f"text {i}" for i in range(BATCH_SIZE * 2 + 5)])
    assert sizes == [BATCH_SIZE, BATCH_SIZE, 5] and len(vectors) == BATCH_SIZE * 2 + 5


async def test_dimensions_are_requested_only_for_models_that_accept_them():
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response([vector(0)]))

    await make(handler, model="text-embedding-3-small").embed(["x"])
    await make(handler, model="text-embedding-ada-002").embed(["x"])
    assert seen[0]["dimensions"] == EMBEDDING_DIMENSIONS
    assert "dimensions" not in seen[1]


async def test_a_wrong_sized_vector_is_an_error_not_silently_stored():
    def handler(request):
        return httpx.Response(200, json=response([[0.1, 0.2, 0.3]]))

    with pytest.raises(EmbeddingError, match="3 dimensions"):
        await make(handler).embed(["x"])


async def test_a_missing_embedding_is_an_error():
    def handler(request):
        return httpx.Response(200, json=response([vector(0)]))  # asked for 2, got 1

    with pytest.raises(EmbeddingError, match="asked for 2"):
        await make(handler).embed(["a", "b"])


async def test_empty_text_does_not_break_a_batch():
    sent: list[list[str]] = []

    def handler(request):
        sent.append(json.loads(request.content)["input"])
        return httpx.Response(200, json=response([vector(0)]))

    await make(handler).embed([""])
    assert sent == [[" "]]


# ------------------------------------------------------------------------------ settings


def test_the_hashing_provider_needs_no_key():
    embedder = build_embedder(Settings(_env_file=None, embedding_provider="hashing"))
    assert isinstance(embedder, HashingEmbedder)


def test_no_key_and_no_hashing_means_no_embedder():
    assert build_embedder(Settings(_env_file=None, openai_api_key=None)) is None


def test_embeddings_do_not_inherit_the_chat_providers_base_url():
    """A chat provider such as DeepSeek or Kimi may not serve embeddings: they have their own settings."""
    settings = Settings(
        _env_file=None, openai_api_key="sk-chat", openai_base_url="https://chat-only.example/v1"
    )
    embedder = build_embedder(settings)
    assert isinstance(embedder, OpenAIEmbedder)
    assert "chat-only" not in str(embedder._client.base_url)

    own = build_embedder(
        Settings(_env_file=None, embedding_api_key="sk-emb", embedding_base_url="https://emb.example/v1")
    )
    assert "emb.example" in str(own._client.base_url)
