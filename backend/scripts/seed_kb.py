"""Loads the demo help articles into each tenant's knowledge base. Idempotent.

Re-running costs nothing for articles whose text did not change (they are skipped before embedding is paid
for). Needs OPENAI_API_KEY for real embeddings, or `--offline` to use the free hashing stand-in (the
search works, but only on shared words, not meaning).

Usage (from backend/):
    python -m scripts.seed_kb
    python -m scripts.seed_kb --offline
"""

import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Employee, KbArticle, Tenant
from app.db.session import AdminSessionLocal, tenant_session
from app.llm.embeddings import HashingEmbedder, build_embedder
from app.services import knowledge_base as kb
from scripts.kb_content import ARTICLES


async def main(offline: bool) -> None:
    embedder = HashingEmbedder() if offline else build_embedder(get_settings())
    if embedder is None:
        raise SystemExit("No embedding provider: set OPENAI_API_KEY in backend/.env, or pass --offline.")
    print(f"embedding model: {embedder.model}")

    async with AdminSessionLocal() as admin:
        tenants = {t.slug: t.id for t in await admin.scalars(select(Tenant))}
        agents = {
            e.tenant_id: e.id
            for e in await admin.scalars(select(Employee).where(Employee.is_support_agent.is_(True)))
        }

    for slug, articles in ARTICLES.items():
        tenant_id = tenants.get(slug)
        if tenant_id is None:
            print(f"skip: tenant '{slug}' does not exist (run scripts.seed_demo_data first)")
            continue
        for title, body in articles:
            async with tenant_session(tenant_id) as session:
                existing = await session.scalar(select(KbArticle).where(KbArticle.title == title))
            prepared = await kb.prepare_article(embedder, title, body)  # no transaction open
            async with tenant_session(tenant_id) as session:
                if existing is None:
                    await kb.create_article(session, tenant_id, agents.get(tenant_id), prepared)
                    print(f"created:   {slug} / {title} ({len(prepared.chunks)} passages)")
                else:
                    _, changed = await kb.replace_article(session, existing.id, prepared)
                    print(f"{'updated:  ' if changed else 'unchanged:'} {slug} / {title}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="use the free hashing embedder")
    asyncio.run(main(parser.parse_args().offline))
