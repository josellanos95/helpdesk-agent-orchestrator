# Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Scaffold (FastAPI, Vite + React + TS + Tailwind) | done |
| M1 | Data model, tenant isolation via Postgres RLS ([ADR 0001](adr/0001-multi-tenant-isolation-via-rls.md)) | done |
| M2 | Isolation tests, migration round-trip test, CI | done |
| M3 | Agent core: tool-calling loop, persisted messages, per-run traces | done (live OpenAI smoke test pending) |
| M4 | Short transactions, exactly-once tool calls, per-conversation lock, `Idempotency-Key` | done |
| M5 | Human approvals for sensitive actions, escalation queue, audit log | done |
| M6 | Per-tenant knowledge base: hybrid search (pgvector + full text), cited answers | done |
| M7 | Responsive web UI: live audit listing, run inspector, approvals queue, knowledge base ([ADR 0006](adr/0006-web-ui-the-audit-listing.md)) | done |
| M8a | Demo protection: signed sessions, server-enforced roles, rate limits, spend caps, housekeeping ([ADR 0007](adr/0007-demo-sessions-limits-and-budget.md)) | done |
| M8b | Evals (behaviour, guardrails, retrieval), model comparison for latency and cost ([ADR 0008](adr/0008-agent-evals.md), [results](evals.md)) | done |
| M9 | Public deployment, README, ADRs, demo video | planned |

## Decisions

- **LLM provider:** OpenAI, `gpt-5-mini` with reasoning effort `low`, chosen by the evals over `gpt-5-nano` and
  over the same model at default effort ([results](evals.md)), behind a thin client interface so it can be swapped.
- **Public demo cost control (M8):** separate API key with a hard monthly limit, a global daily cap in the app,
  per-session and per-IP limits, and a replay mode with recorded runs once the cap is reached. Evals use their
  own key and budget.
- **Bring-your-own-key (M8, optional):** any OpenAI-compatible endpoint; the key is used per request, never
  stored or logged, and `base_url` is restricted to an allowlist.

## Hosting (decided at M9; everything runs locally until then)

The old managed deployment is gone. The plan is a single VPS running Docker Compose (API, Postgres with
pgvector, Redis) behind Caddy with automatic HTTPS, the frontend on Vercel, and deployment from GitHub
Actions over SSH using a dedicated, non-root deploy key.
