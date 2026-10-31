# Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Scaffold (FastAPI, Vite + React + TS + Tailwind) | done |
| M1 | Data model, tenant isolation via Postgres RLS ([ADR 0001](adr/0001-multi-tenant-isolation-via-rls.md)) | done |
| M2 | Isolation tests, migration round-trip test, CI | done |
| M3 | Agent core: tool-calling loop, persisted messages, per-run traces | done (live OpenAI smoke test pending) |
| M4 | Short transactions, exactly-once tool calls, per-conversation lock, `Idempotency-Key` | done |
| M5 | Human approvals for sensitive actions, escalation queue | planned |
| M6 | Per-tenant knowledge base with RAG (pgvector) | planned |
| M7 | UI: chat, agent console, run inspector | planned |
| M8 | Evals, guardrails, spend caps, demo authentication | planned |
| M9 | Public deployment, README, ADRs, demo video | planned |

## Decisions

- **LLM provider:** OpenAI. The model is chosen by the eval results (candidates: `gpt-5-mini`, `gpt-5-nano`),
  behind a thin client interface so it can be swapped.
- **Public demo cost control (M8):** separate API key with a hard monthly limit, a global daily cap in the app,
  per-session and per-IP limits, and a replay mode with recorded runs once the cap is reached. Evals use their
  own key and budget.
- **Bring-your-own-key (M8, optional):** any OpenAI-compatible endpoint; the key is used per request, never
  stored or logged, and `base_url` is restricted to an allowlist.

## Hosting (decided at M9; everything runs locally until then)

The old managed deployment is gone. The plan is a single VPS running Docker Compose (API, Postgres with
pgvector, Redis) behind Caddy with automatic HTTPS, the frontend on Vercel, and deployment from GitHub
Actions over SSH using a dedicated, non-root deploy key.
