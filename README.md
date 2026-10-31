# Triagent

[![CI](https://github.com/josellanos95/helpdesk-agent-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/josellanos95/helpdesk-agent-orchestrator/actions/workflows/ci.yml)

Multi-tenant AI agent for IT helpdesk support — tool use / function calling, Redis-coordinated session state, idempotent execution, and human-in-the-loop escalation. Built with FastAPI + OpenAI.

🚧 Work in progress. Full README with architecture, demo link, and design decisions coming as the project reaches completion.

## Status

| Milestone | | |
|---|---|---|
| M0 | Scaffold (FastAPI, Vite + React + TS + Tailwind) | done |
| M1 | Data model with real tenant isolation via Postgres RLS ([ADR 0001](docs/adr/0001-multi-tenant-isolation-via-rls.md)) | done |
| M2 | Isolation tests, migration round-trip test, CI | done |
| M3+ | Agent core, idempotency, approvals, knowledge base, UI, evals | planned |

## Local development

```bash
docker compose up -d        # Postgres + Redis

cd backend
python -m venv .venv && .venv/Scripts/activate  # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head && python -m scripts.seed_demo_data
uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev
```

## Tests

```bash
cd backend
pytest
```

The suite talks to a real Postgres — Row Level Security is a database feature, so a mock would prove
nothing. It uses a separate `<dbname>_test` database (created on demand from `DATABASE_URL`), never
the development one.

What the isolation tests cover: the runtime role cannot bypass RLS; RLS is enabled, forced and has a
policy on every tenant table; any new table with a `tenant_id` must be registered (otherwise the
suite fails); a tenant-scoped session sees only its own rows, even when the query explicitly asks for
another tenant's; cross-tenant inserts, moves, updates and deletes are blocked; the tenant never
outlives its transaction on a reused pooled connection; concurrent requests for different tenants do
not mix.

One migration test (`downgrade` → `upgrade` round trip) is skipped when another database on the same
Postgres server still depends on the `app_runtime` role, because Postgres roles are cluster-wide.
It always runs in CI, which starts from a clean server.
