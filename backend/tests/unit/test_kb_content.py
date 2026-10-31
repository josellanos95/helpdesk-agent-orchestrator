"""The demo knowledge base, its gold questions and the limits must stay consistent."""

import json
from pathlib import Path

import pytest

from app.services import knowledge_base as kb
from app.services.chunking import chunk_text
from scripts.kb_content import ARTICLES

GOLD = json.loads((Path(__file__).resolve().parents[2] / "evals" / "retrieval_gold.json").read_text("utf-8"))


@pytest.mark.parametrize(
    ("tenant", "title", "body"), [(t, a, b) for t, items in ARTICLES.items() for a, b in items]
)
def test_every_demo_article_is_ingestable(tenant, title, body):
    assert len(title) >= 3 and len(body) <= kb.MAX_BODY_CHARS
    assert 1 <= len(chunk_text(body)) <= kb.MAX_CHUNKS_PER_ARTICLE


def test_titles_are_unique_within_a_tenant():
    for tenant, items in ARTICLES.items():
        titles = [title for title, _ in items]
        assert len(titles) == len(set(titles)), tenant
        assert len(titles) <= kb.MAX_ARTICLES_PER_TENANT


def test_every_gold_question_points_at_an_article_that_exists():
    for item in GOLD:
        titles = {title for title, _ in ARTICLES[item["tenant"]]}
        assert item["expected"] is None or item["expected"] in titles, item


def test_the_gold_set_covers_every_tenant_and_has_unanswerable_questions():
    assert {item["tenant"] for item in GOLD} == set(ARTICLES)
    assert sum(item["expected"] is None for item in GOLD) >= 5  # false accepts are measured, not assumed
    assert len({item["query"] for item in GOLD}) == len(GOLD)


def test_one_question_is_deliberately_about_another_tenants_content():
    """Globex is asked about Acme's CRM: documentation that exists, but not for them, must not be found."""
    leaked = [i for i in GOLD if i["tenant"] == "globex" and "Northwind" in i["query"]]
    assert leaked and all(i["expected"] is None for i in leaked)
    assert not any("Northwind" in body for _, body in ARTICLES["globex"])
