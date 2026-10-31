# Findings and debt log

Things noticed while building, with the milestone where each should be dealt with. Fixed items stay
listed (struck through) so the history of what the project learned is not lost.

## Open

| # | Finding | Found in | Fix in |
|---|---|---|---|
| 2 | The ledger only stops repeats of the same `tool_call_id`. A model that asks twice with two different ids still opens two tickets. | M4 | M8 (eval case: exactly one ticket) |
| 6 | Identity is still *chosen*: anyone can mint a signed session for any fictitious person (M8a made the server enforce that choice, ADR 0007). Header mode, used in development and tests, still trusts the caller and must never be exposed. | M1, M5 | accept for the demo; real accounts only if the product leaves demo status |
| 7 | Latency: 20-30 s for a full turn with `gpt-5-mini` (the last model call alone up to 15 s). | M3 live test | M8 (compare models/reasoning effort), M7 (stream the reply) |
| 8 | The model marks "degraded" systems `urgent` although the tool says urgent is for fully blocked work. | M3 live test | M8 (eval case) |
| 9 | Prompt fixes (no ticket for refused requests, no invented capabilities) were checked on single samples only. | M3 live test | M8 (eval suite) |
| 10 | Price table in `app/llm/pricing.py` comes from third-party trackers, has no entry for DeepSeek/Kimi/other providers. | M3 | M8 (verify against official pages when a provider is chosen) |
| 12 | `openai` SDK is pinned to 1.59.6, older than the gpt-5 family. Works for plain chat + tools; newer parameters (e.g. reasoning effort) are not typed. | M3 | M8 |
| 13 | `gpt-5-mini`-style models reject custom sampling parameters; the client sends none, and a test enforces it. Other providers may differ. | M3 | M8 |
| 14 | The public Vercel deploy still points at a backend that no longer exists (the UI itself is done). | M0 | M9 |
| 15 | Hosting not decided/provisioned (VPS plan in [roadmap](roadmap.md)). | M3 | M9 |
| 16 | GitHub repository and local folder still named `helpdesk-agent-orchestrator`; README badge and Vercel project use the old name. | M2 | M9 (rename together with deployment) |
| 17 | Downgrade/upgrade migration test is skipped locally when another database on the server uses the `app_runtime` role. | M2 | none (runs in CI) |
| 20 | The conversation lock is a TTL lock, not a fencing token: a run that loses it can still finish the step it is in. Bounded by per-step transactions and the ledger. | M4 | accept / revisit if multi-instance |
| 24 | Escalations have no assignee; who acknowledged one only exists in the audit log (the Queue screen cannot show it either). | M5 | M8 |
| 25 | `reset_password` / `grant_system_access` are simulated (audit record only); identity verification of the requester is delegated to the human approver. | M5 | accept (document in README) |
| 26 | Approval behaviour is only spot-checked with the live model (7 turns, all as intended after the fixes below). Needs eval cases: claims success while pending? re-asks? skips approval under pressure? | M5 | M8 eval cases |
| 27 | In a live run the agent offered to "request temporary access to a backup system" unprompted (offers are free, but it should only offer what the tools can do for that employee). | M5 live test | M8 (eval case) |
| 28 | Retrieval gold set: 26 questions written by the same author as the corpus, so it flatters. Needs more, harder, independently written questions, tracked per release. | M6 | M8 |
| 29 | No reranker. Not needed at 18 articles; revisit when a tenant's KB grows. | M6 | M8 / later |
| 30 | Query embeddings are made inside the agent step's transaction (ADR 0005). Their cost is now counted in the run and the caps (M8a); it is an estimate (4 characters per token), and the embedding still happens inside the step. | M6 | M8b (pre-embed outside the step) |
| 31 | Full-text side is `english` only; a Spanish KB loses the keyword benefit. | M6 | M8 / when multi-language |
| 32 | The agent says things like "I opened a ticket with HR" although tickets have no team routing. Overclaim by omission. | M6 live test | M8 eval case |
| 33 | Prompt-injection through KB content survived one live attempt (single sample, one model). | M6 live test | M8 adversarial eval set |
| 37 | The UI polls (about 1 request/s while a turn runs) instead of streaming; SSE would cut requests and show model tokens as they arrive. | M7 | later |
| 38 | Only the interface is translated (EN/ES); agent replies follow the model, article texts stay as written, and the full-text search is English-only (item 31). | M7 | M8 / later |
| 39 | In a live run the agent printed the raw approval id (a UUID) to the employee. M8a added a prompt rule; it has not been checked against the live model yet. | M7 live test | M8b (eval case) |
| 40 | The UI has been looked at in Chrome only (desktop width and a 390 px frame), not on a real phone or in Safari/Firefox. No automated visual or accessibility test beyond Testing Library. | M7 | M8 / M9 |
| 41 | Sessions cannot be revoked, only expire (12 h); rotating `DEMO_TOKEN_SECRET` kills all of them. | M8a | accept |
| 42 | When the daily budget is spent the demo is read-only until midnight UTC. A replay mode with recorded runs (roadmap) would keep it showable. | M8a | M8b / M9 |
| 43 | The per-IP daily cap is shared by everyone behind one NAT (a company network). Raise or disable `IP_DAILY_BUDGET_USD` if visitors report it. | M8a | watch after M9 |
| 44 | Spend is checked before a run and recorded after it, so a run can overshoot a cap by its own cost (cents at most). | M8a | accept |
| 45 | Bring-your-own-key (roadmap) is not built: sessions always spend the demo's key. | M8a | M8b / later |
| 35 | Changing the embedding model leaves old chunks unsearchable until `seed_kb` re-embeds; vector width (1536) is fixed by the schema. | M6 | documented; M8 re-embed command |
| 19 | No automated live-model check in CI (costs money, non-deterministic). | M3 | M8 (manual/weekly eval job with its own key) |

## Needs the owner

- Create a dedicated OpenAI project/key for Triagent with a monthly limit and update `backend/.env` and the
  Windows machine variable. The old key (`...CwkcA`) is rejected by OpenAI and is also used by DocuRAG, AI
  Interview Copilot and Estadisticas Boca.
- Optional cheaper provider (DeepSeek, Kimi, ...): send an OpenAI-compatible base URL, model name and prices.

## Fixed

- ~~Agent opened a ticket for questions it could not answer, right after offering to~~ (M6 live test: two prompt
  rules collided, "unsolvable -> open a ticket" vs "offer and wait". Split into PROBLEM vs QUESTION. Re-run: offers,
  waits, opens on "yes", and still opens proactively for a real blocking problem).
- ~~`PUT` of identical article content still requested embeddings before noticing nothing changed~~ (M6: the
  hash is compared first; a test asserts zero extra embeddings).
- ~~Full-text search required every query word to be in a passage, so natural questions missed~~ (M6: ranking
  uses OR, the relevance gate keeps AND).
- ~~The dev Postgres image had no pgvector~~ (M6: compose and CI use `pgvector/pgvector:pg16`; the local volume was
  recreated because the old image's collation, musl, differs from the Debian one and could corrupt text indexes).

- ~~Live run: after an approval the model said "I couldn't verify that the reset completed" and opened a
  needless ticket, ignoring the approval message in the conversation~~ (M5: `list_my_requests` tool + prompt;
  re-run: one tool call, correct answer, no ticket).

- ~~**Tests run with explicit paths used the development database.**~~ (M5, found 2026-10-31.) The harness set
  the test `DATABASE_URL` in `pytest_configure`, which pytest calls *after* importing the conftest files of
  paths named on the command line, so `pytest tests/integration/test_x.py` cached the settings and built the
  engines against the development database. The full-suite command (`pytest`) was unaffected. Effect: the
  seed test deleted the demo tenants `acme`, `globex` and `initech` from the dev DB (fictitious data, restored
  with `python -m scripts.seed_demo_data`; the earlier smoke-test conversation and tickets are gone), and
  earlier explicit-path runs created and removed test rows there. Fix: configuration now happens when
  `tests/conftest.py` is imported, plus a session fixture that aborts the run unless every setting and engine
  points at a `*_test` database and Redis db 15; both are tested.
- ~~`audit_log` was append-only by convention only~~ (M5: the app role has no UPDATE/DELETE, tested).

- ~~Transaction held open across every model call~~ (M4, a transaction per step; a test watches `pg_stat_activity`).
- ~~Retried requests and replayed tool calls could run twice~~ (M4: `Idempotency-Key`, tool ledger).
- ~~Concurrent messages on one conversation interleaved~~ (M4: Redis lock, 409).
- ~~OpenAI client had a 10-minute timeout, longer than the lock TTL~~ (M4: 45 s + 1 retry).
- ~~Environment variable overriding `.env` was undocumented~~ (M4, README).
- ~~An abandoned `in_progress` idempotency claim would return 409 forever~~ (M4, stale takeover).

- ~~RLS migration imported the live table list, so it would break a fresh `upgrade head` once tables were
  added~~ (M3).
- ~~Message order relied on `created_at`, which ties inside a transaction~~ (M3, `messages.seq`).
- ~~ADR 0001 claimed a missing tenant scope always errors; a fresh connection returns zero rows~~ (M2).
- ~~Agent opened tickets for refused requests, promised actions it cannot perform and invented a "support
  portal"~~ (M3, prompt rules).
- ~~GitHub tokens embedded in the remotes of ObraBot and Tribunero~~ (outside this repo).

- ~~UI treatment of provider failures, a busy conversation (409) and unsent messages~~ (M7: `FAILED` and `NOT SENT`
  stamps, automatic retry with the same `Idempotency-Key`; items 11, 21, 22).

- ~~Runs stay `running` if the process is killed outright (no handler runs). Exceptions already mark the run failed.~~ (M8a: the sweeper closes runs left `running` for over 10 minutes)
- ~~`Idempotency-Key` rows never expire.~~ (M8a: the sweeper drops idempotency keys older than 24 h)
- ~~Expired approvals stay `pending` until someone tries to decide them and the employee is never told.~~ (M8a: the sweeper expires unsigned approvals and tells the employee in the conversation)
- ~~`/api/kb/search` and article writes are unthrottled; each call spends embedding money.~~ (M8a: per-session rate limits and spend caps on search and article writes)
