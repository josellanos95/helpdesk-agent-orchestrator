"""Measures how well search finds the right article, with the configured (real) embedding model.

For every question in evals/retrieval_gold.json it records what came back, then prints, for several
relevance thresholds:
  - hit@1 / hit@3: the expected article is first / among the top three (questions that have an answer)
  - false accepts: unanswerable questions that still returned something (noise the agent would be given)
  - misses: answerable questions that returned nothing (the agent would wrongly say "no documentation")

The point is to choose `KB_MIN_SIMILARITY` from data instead of guessing. It costs a fraction of a cent.

Usage (from backend/, with the demo KB loaded):
    python -m scripts.eval_retrieval
    python -m scripts.eval_retrieval --offline        # free hashing stand-in, only to test the script
    python -m scripts.eval_retrieval --verbose
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Tenant
from app.db.session import AdminSessionLocal, tenant_session
from app.llm.embeddings import HashingEmbedder, build_embedder
from app.services import knowledge_base as kb

GOLD = Path(__file__).resolve().parents[1] / "evals" / "retrieval_gold.json"
THRESHOLDS = [0.0, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]


async def main(offline: bool, verbose: bool) -> None:
    embedder = HashingEmbedder() if offline else build_embedder(get_settings())
    if embedder is None:
        raise SystemExit("No embedding provider: set OPENAI_API_KEY, or pass --offline.")
    gold = json.loads(GOLD.read_text(encoding="utf-8"))

    async with AdminSessionLocal() as admin:
        tenants = {t.slug: t.id for t in await admin.scalars(select(Tenant))}

    rows = []
    for item in gold:
        [vector] = await embedder.embed([item["query"]])
        async with tenant_session(tenants[item["tenant"]]) as session:
            # threshold 0 and no keyword gate: keep the raw ranking and filter per threshold below
            hits = await kb.search_by_vector(
                session, vector, item["query"], model=embedder.model, top_k=8, min_similarity=-1.0
            )
        rows.append((item, hits))
        if verbose:
            top = hits[0] if hits else None
            sim = f"{top.similarity:.3f}" if top and top.similarity is not None else "  -  "
            print(
                f"[{item['tenant']:7}] sim={sim} kw={bool(top and top.keyword_match)!s:5} "
                f"top={top.title if top else '-':32} want={item['expected']}  | {item['query']}"
            )

    answerable = [(i, h) for i, h in rows if i["expected"]]
    unanswerable = [(i, h) for i, h in rows if not i["expected"]]
    print(f"\nmodel: {embedder.model}   answerable: {len(answerable)}   unanswerable: {len(unanswerable)}\n")
    print(f"{'min_sim':>8} {'hit@1':>7} {'hit@3':>7} {'misses':>7} {'false accepts':>14}")
    for threshold in THRESHOLDS:

        def passing(hits, threshold=threshold):
            return [
                h for h in hits if h.keyword_match or (h.similarity is not None and h.similarity >= threshold)
            ]

        h1 = h3 = misses = 0
        for item, hits in answerable:
            kept = passing(hits)
            titles = [h.title for h in kept]
            h1 += bool(titles and titles[0] == item["expected"])
            h3 += item["expected"] in titles[:3]
            misses += not kept
        false_accepts = sum(bool(passing(hits)) for _, hits in unanswerable)
        n = len(answerable)
        row = f"{threshold:>8.2f} {h1 / n:>7.0%} {h3 / n:>7.0%} {misses:>7}"
        print(f"{row} {false_accepts:>11}/{len(unanswerable)}")

    chosen = get_settings().kb_min_similarity
    print(f"\nBy kind of question, at the configured KB_MIN_SIMILARITY={chosen}:")
    print(f"{'kind':>14} {'n':>3} {'hit@1':>7} {'hit@3':>7} {'misses':>7} {'false accepts':>14}")
    for kind in dict.fromkeys(item.get("kind", "core") for item, _ in rows):
        group = [(i, h) for i, h in rows if i.get("kind", "core") == kind]

        def kept(hits):
            return [
                h for h in hits if h.keyword_match or (h.similarity is not None and h.similarity >= chosen)
            ]

        have = [(i, kept(h)) for i, h in group if i["expected"]]
        none = [(i, kept(h)) for i, h in group if not i["expected"]]
        if have:
            h1 = sum(bool(k and k[0].title == i["expected"]) for i, k in have)
            h3 = sum(i["expected"] in [x.title for x in k[:3]] for i, k in have)
            cells = f"{h1 / len(have):>7.0%} {h3 / len(have):>7.0%} {sum(not k for _, k in have):>7}"
        else:
            cells = f"{'-':>7} {'-':>7} {'-':>7}"
        false = f"{sum(bool(k) for _, k in none):>11}/{len(none)}" if none else f"{'-':>14}"
        print(f"{kind:>14} {len(group):>3} {cells} {false}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.offline, args.verbose))
