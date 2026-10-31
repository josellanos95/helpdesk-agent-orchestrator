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
| M3 | Agent core: tool-calling loop, persisted messages, per-run traces ([ADR 0002](docs/adr/0002-agent-loop.md)) | done, live OpenAI smoke test pending |
| M4 | Short transactions, exactly-once tool calls, per-conversation lock, `Idempotency-Key` ([ADR 0003](docs/adr/0003-idempotency-locks-short-transactions.md)) | done |
| M5+ | Approvals, knowledge base, UI, evals | planned |

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

## API (M3)

All routes take the tenant in an `X-Tenant-Id` header (temporary; real auth comes in M8).

| Route | |
|---|---|
| `GET /api/employees` | Employees of the tenant (for the demo picker) |
| `POST /api/conversations` | Start a conversation as an employee |
| `POST /api/conversations/{id}/messages` | Send a message; runs the agent and returns the reply plus run totals |
| `GET /api/conversations/{id}/messages` | Full history, including tool calls and results |
| `GET /api/runs/{id}` | The trace: every model call and tool call with latency, tokens and errors |

`POST .../messages` accepts an optional `Idempotency-Key` header (a retry with the same key and body replays the
stored reply instead of running the agent again). It answers `409` while another message of the same conversation
is being processed, and `503` if Redis is unavailable.

Try the real agent from a terminal (needs `OPENAI_API_KEY` in `backend/.env`):
`python -m scripts.chat_cli --tenant acme --employee alice --trace`

### Configuration gotcha

An environment variable beats `backend/.env`. If `OPENAI_API_KEY` is also set as a system or user variable
(Windows: *Environment Variables*), editing the `.env` file changes nothing. `OPENAI_BASE_URL` points the client at
any OpenAI-compatible provider.

## Tests

```bash
cd backend
pytest
```

The suite needs Postgres and Redis (`docker compose up -d`). It talks to the real ones — Row Level Security is a database feature, so a mock would prove
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
