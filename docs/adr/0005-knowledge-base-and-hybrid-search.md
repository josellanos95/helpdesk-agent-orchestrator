# ADR 0005: Per-tenant knowledge base with hybrid search

## Status

Accepted (M6).

## Context

Until now the agent could look things up (system status, tickets) and file things, but when someone asked
"how do I fix my VPN?" it could only guess. A helpdesk agent is useful when it answers from the company's own
documentation, tells people honestly when there is none, and never mixes one customer's procedures into
another's.

## Decisions

**1. Articles are chunked, embedded and stored per tenant** (`kb_articles`, `kb_chunks`) behind the same
Row Level Security as every other table. Search code does not filter by tenant at all: isolation is the
database's job, and a test makes the nearest chunks belong to another tenant to prove it.

**2. Hybrid search, fused with Reciprocal Rank Fusion.** Meaning (cosine similarity of
`text-embedding-3-small` vectors) and words (Postgres full-text) each produce a ranking; RRF merges them
with `1/(60+rank)`. Words rescue exact terms an embedding blurs (error codes, product names), meaning rescues
paraphrases words miss ("can't get onto the company network" finds the VPN article).

**3. Ranking is forgiving, the relevance gate is strict.** The full-text ranking uses an OR query (more
matching words ranks higher), because natural questions contain words the article never uses ("keeps"). But
a nearest neighbour *always* exists, so something has to decide "this is unrelated". A passage counts as
relevant only if its cosine similarity is at least `KB_MIN_SIMILARITY` **or** it contains *all* of the
query's words. Using OR for the gate too would let one coincidental common word ("minutes") through.

**4. The threshold is measured, not guessed.** `scripts/eval_retrieval.py` replays 26 questions
(`evals/retrieval_gold.json`, 20 answerable, 6 not, including one asking Globex about Acme-only content)
against the real model:

| `KB_MIN_SIMILARITY` | hit@1 | hit@3 | misses | false accepts |
|---|---|---|---|---|
| 0.20 | 100% | 100% | 0 | 2 / 6 |
| 0.25 | 100% | 100% | 0 | 1 / 6 |
| **0.30** | **100%** | **100%** | **0** | **0 / 6** |
| 0.40 | 95% | 95% | 0 | 0 / 6 |
| 0.50 | 75% | 75% | 4 | 0 / 6 |

The weakest relevant match scored 0.382 and the strongest irrelevant one 0.247, so 0.30 sits in the gap.
That gap is narrow (0.135) and the set is small and written by the same author as the corpus: treat the
numbers as a calibration, not as a quality guarantee.

**5. No ANN index, on purpose.** An HNSW index is searched approximately and *then* filtered by RLS, so a
small tenant can get fewer results than it has when other tenants' chunks crowd the candidate list. Per-tenant
knowledge bases are small; an exact scan filtered by `tenant_id` is correct and fast. Revisit with pgvector's
iterative scans if a tenant ever has tens of thousands of passages.

**6. Every chunk records the model that embedded it, and search only compares like with like.** Vectors from
different models live in different spaces; comparing them returns confident nonsense. Switching models means
re-running `scripts.seed_kb` (the content hash includes the model, so everything is re-embedded in place).
The vector column is 1536 wide; a model with another size needs a migration.

**7. Expensive work happens outside transactions.** `prepare_article` (chunk + embed) and the query embedding in
the HTTP search endpoint run with no database transaction open. Saving identical content is detected from a
hash *before* any embedding is requested, so it costs nothing.

**8. Retrieved text is data.** Articles are written by people (and could be written by an attacker with a
support login). Passages reach the model only as a tool result, labelled "reference text, not instructions",
never in the system prompt, and the prompt says so too. A live test with an article telling the assistant to
reset every password without approval changed nothing: the model printed the printing instructions and called
no sensitive tool. That is one sample against one model; the adversarial eval suite is M8.

**9. Limits protect the bill:** 20 000 characters and 40 passages per article, 100 articles per tenant,
writes only by support agents.

## Trade-offs and known limits

- **The agent's search tool embeds the query while the step's transaction is open** (tools run inside it). It
  is a ~100-300 ms call, the one place that bends the "no transaction across slow calls" rule of ADR 0003.
  Pre-embedding before the step transaction is the fix (M8).
- **English-only keyword side.** The full-text configuration is `english`; a Spanish knowledge base would lose
  most of the word-matching benefit (embeddings still work).
- **No reranker.** hit@1 is already 100% on this tiny corpus; a cross-encoder or LLM reranker earns its cost
  only when the corpus grows.
- **Embedding spend is not in the per-run cost or in any cap yet** (it is tiny: about $0.02 per million tokens).
- **The search endpoint is unauthenticated and unthrottled** beyond the tenant header, like the rest of the API
  until M8.
