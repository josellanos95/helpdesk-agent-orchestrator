# Findings and debt log

Things noticed while building, with the milestone where each should be dealt with. Fixed items stay
listed (struck through) so the history of what the project learned is not lost.

## Open

| # | Finding | Found in | Fix in |
|---|---|---|---|
| 2 | The ledger only stops repeats of the same `tool_call_id`. A model that asks twice with two different ids still opens two tickets. | M4 | M8 (eval case: exactly one ticket) |
| 4 | Runs stay `running` if the process is killed outright (no handler runs). Exceptions already mark the run failed. | M4 | M8 (reaper for runs older than the lock TTL) |
| 5 | `Idempotency-Key` rows never expire. | M4 design | M8 |
| 6 | Tenant identity is the `X-Tenant-Id` header: RLS stops query bugs, not impersonation. | M1 | M8 (signed demo tokens) |
| 7 | Latency: 20-30 s for a full turn with `gpt-5-mini` (the last model call alone up to 15 s). | M3 live test | M8 (compare models/reasoning effort), M7 (stream the reply) |
| 8 | The model marks "degraded" systems `urgent` although the tool says urgent is for fully blocked work. | M3 live test | M8 (eval case) |
| 9 | Prompt fixes (no ticket for refused requests, no invented capabilities) were checked on single samples only. | M3 live test | M8 (eval suite) |
| 10 | Price table in `app/llm/pricing.py` comes from third-party trackers, has no entry for DeepSeek/Kimi/other providers. | M3 | M8 (verify against official pages when a provider is chosen) |
| 11 | Provider failures (bad key, outage) return HTTP 200 with `run.status = "failed"`. Fine for the transcript, but the UI needs to treat it as an error state. | M3 live test | M7 |
| 12 | `openai` SDK is pinned to 1.59.6, older than the gpt-5 family. Works for plain chat + tools; newer parameters (e.g. reasoning effort) are not typed. | M3 | M8 |
| 13 | `gpt-5-mini`-style models reject custom sampling parameters; the client sends none, and a test enforces it. Other providers may differ. | M3 | M8 |
| 14 | Frontend is only a status page; the public Vercel deploy still points at a backend that no longer exists. | M0 | M7 / M9 |
| 15 | Hosting not decided/provisioned (VPS plan in [roadmap](roadmap.md)). | M3 | M9 |
| 16 | GitHub repository and local folder still named `helpdesk-agent-orchestrator`; README badge and Vercel project use the old name. | M2 | M9 (rename together with deployment) |
| 17 | Downgrade/upgrade migration test is skipped locally when another database on the server uses the `app_runtime` role. | M2 | none (runs in CI) |
| 20 | The conversation lock is a TTL lock, not a fencing token: a run that loses it can still finish the step it is in. Bounded by per-step transactions and the ledger. | M4 | accept / revisit if multi-instance |
| 21 | A conversation can only be touched through the API process that holds the lock; a user message rejected with 409 is lost and the UI must offer to resend it. | M4 | M7 |
| 19 | No automated live-model check in CI (costs money, non-deterministic). | M3 | M8 (manual/weekly eval job with its own key) |

## Needs the owner

- Create a dedicated OpenAI project/key for Triagent with a monthly limit and update `backend/.env` and the
  Windows machine variable. The old key (`...CwkcA`) is rejected by OpenAI and is also used by DocuRAG, AI
  Interview Copilot and Estadisticas Boca.
- Optional cheaper provider (DeepSeek, Kimi, ...): send an OpenAI-compatible base URL, model name and prices.

## Fixed

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
