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
| M5 | Human approval of sensitive actions, escalation queue, audit log ([ADR 0004](docs/adr/0004-human-approvals-and-escalation.md)) | done |
| M6 | Per-tenant knowledge base: hybrid search (pgvector + full text), cited answers ([ADR 0005](docs/adr/0005-knowledge-base-and-hybrid-search.md)) | done |
| M7 | Responsive web UI: the agent's work printed live as an audit listing ([ADR 0006](docs/adr/0006-web-ui-the-audit-listing.md)) | done |
| M8a | Demo protection: signed sessions, server-enforced roles, rate limits and spend caps ([ADR 0007](docs/adr/0007-demo-sessions-limits-and-budget.md)) | done |
| M8b | Behaviour evals, model and reasoning-effort comparison, bigger retrieval set ([ADR 0008](docs/adr/0008-agent-evals.md), [results](docs/evals.md)) | done |
| M9 | Deploy | planned |

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

In `AUTH_MODE=header` (local development, the default) routes take the tenant in an `X-Tenant-Id` header and nobody is authenticated. In `AUTH_MODE=signed` (required in production) every route needs `Authorization: Bearer <token>` from `POST /api/demo/session`, and the token decides tenant, person and role (see [Demo protection](#demo-protection)).

| Route | |
|---|---|
| `GET /api/employees` | Employees of the tenant (for the demo picker) |
| `POST /api/conversations` | Start a conversation as an employee |
| `POST /api/conversations/{id}/messages` | Send a message; runs the agent and returns the reply plus run totals |
| `GET /api/conversations/{id}/messages` | Full history, including tool calls and results |
| `GET /api/runs/{id}` | The trace: every model call and tool call with latency, tokens and errors |

The human side (until real authentication exists the acting support agent is sent as `approver_id`):

| Route | |
|---|---|
| `GET /api/approvals?status=pending\|approved\|rejected\|expired\|all` | Sensitive requests waiting for a decision |
| `POST /api/approvals/{id}/decision` | `{decision: approve\|reject, approver_id, note}`; approving runs the action once |
| `GET /api/escalations?status=open\|all\|pending\|acknowledged\|resolved` | The human support queue |
| `POST /api/escalations/{id}/acknowledge` / `resolve` | Work an escalation |

`POST .../messages` accepts an optional `Idempotency-Key` header (a retry with the same key and body replays the
stored reply instead of running the agent again). It answers `409` while another message of the same conversation
is being processed, and `503` if Redis is unavailable.

Try the real agent from a terminal (needs `OPENAI_API_KEY` in `backend/.env`):
`python -m scripts.chat_cli --tenant acme --employee alice --trace`

### Configuration gotcha

An environment variable beats `backend/.env`. If `OPENAI_API_KEY` is also set as a system or user variable
(Windows: *Environment Variables*), editing the `.env` file changes nothing. `OPENAI_BASE_URL` points the client at
any OpenAI-compatible provider.

## Knowledge base

The agent answers how-to questions from each company's own articles, cites the article, and says so when
there is no documentation instead of improvising.

```bash
docker compose up -d          # Postgres now comes with pgvector
cd backend
python -m scripts.seed_kb               # embeds the demo articles (needs OPENAI_API_KEY)
python -m scripts.seed_kb --offline     # free, lexical-only stand-in, for working without a key
python -m scripts.eval_retrieval --verbose
```

Measured with `text-embedding-3-small` on 63 questions (45 answerable, 18 not: paraphrases, typos, Spanish,
undocumented topics and another company's topics): **hit@1 100%, hit@3 100%, no answer missed** at the default
`KB_MIN_SIMILARITY=0.30`, at the price of 5 of the 18 unanswerable questions returning an irrelevant passage
that the agent has to recognise (it did, in every eval run). Per-kind numbers and the threshold trade-off are in
[docs/evals.md](docs/evals.md). Same author as the corpus: a calibration, not a guarantee (ADR 0005).

| Route | |
|---|---|
| `GET /api/kb/articles`, `GET /api/kb/articles/{id}` | List / read |
| `POST /api/kb/articles`, `PUT /api/kb/articles/{id}`, `DELETE /api/kb/articles/{id}?actor_id=` | Write (support agents only; identical content is not re-embedded) |
| `POST /api/kb/search` | What the agent would be given for a question, with scores |

## Web app

```bash
docker compose up -d && cd backend && uvicorn app.main:app --port 8000     # API (needs OPENAI_API_KEY in backend/.env)
cd frontend && npm install && npm run dev                                    # http://localhost:5173, proxies /api to :8000
npm test                                                                     # Vitest: line mapping, API client, i18n, send flow, components
```

Pick a fictitious company and a person. The server mints a signed session for that choice and enforces it; the identity is still **chosen, not authenticated** (anyone can be anyone in the demo, with fictitious data).

- **Employee:** Chat, Requests, Knowledge. Ask the agent something and watch each step print as a line with its
  real time, duration, tokens and cost; click a line to inspect its input and output. A request that needs a
  human waits as an `AWAITING` line.
- **Support agent:** Queue (sign or reject approvals with a note, work escalations), Chats (read-only view of any
  conversation), Knowledge (edit articles, test the search with similarity bars).
- Works on a phone (bottom tab bar, inspector as a bottom sheet) and on a desktop (three columns). English and
  Spanish for the interface, light and dark themes.

Extra read routes the UI uses: `GET /api/conversations`, `GET /api/conversations/{id}/runs`, `GET /api/tickets`.

## Evals

The agent is tested against the real model, not only a scripted one. `backend/evals/` holds 28 conversations with
deterministic checks over tool calls and database rows (one ticket not three, a password reset still `pending`, no
internal id in the reply, an order planted in an article ignored), played by throwaway employees in throwaway copies
of the demo companies and deleted afterwards.

```bash
cd backend
python -m scripts.run_evals --repeat 3 --max-usd 0.30        # about 15 cents with the default model
python -m scripts.run_evals --regrade evals/results/*.json   # re-grade saved runs, free
```

Result for the shipped configuration, `gpt-5-mini` with `OPENAI_REASONING_EFFORT=low`: **83 of 84 runs pass, median
4.9 s and $0.0015 per turn**; the same model at its default effort is twice as slow and twice as expensive for the
same pass rate, and `gpt-5-nano` fails guardrails the larger model holds. The comparison, what the evals caught, what
they could not show and what they cost (about $1.9) are in [docs/evals.md](docs/evals.md).

## Demo protection

Because the agent calls a paid model, the public demo is bounded (ADR 0007):

| Setting | Default | |
|---|---|---|
| `AUTH_MODE` | `header` | `signed` makes every route need a session token. `ENVIRONMENT=production` refuses to start unless it is `signed` and `DEMO_TOKEN_SECRET` has 32+ characters. |
| `SESSION_BUDGET_USD` / `IP_DAILY_BUDGET_USD` / `DAILY_BUDGET_USD` | 0.10 / 0.25 / 1.00 | Spend caps (chat, tools and embeddings). `0` switches one off. A reached cap answers `429` with a code the UI shows. |
| `TRUST_FORWARDED_FOR` | `false` | Only behind a trusted reverse proxy. |

Also: per-session and per-IP rate limits (messages, knowledge search and writes, session creation), `GET
/api/demo/budget` for the remaining budget, and a background sweeper that closes stuck runs, expires unsigned
approvals (telling the employee) and drops old idempotency keys.

## Tests

```bash
cd backend
pytest
```

The suite needs Postgres and Redis (`docker compose up -d`; Postgres must have pgvector, which the compose image does). It talks to the real ones — Row Level Security is a database feature, so a mock would prove
nothing. It uses a separate `<dbname>_test` database and Redis database 15 (created on demand from `DATABASE_URL`), never
the development one. This is enforced, not just a convention: the harness points the app at the test
services when `tests/conftest.py` is imported, and a session fixture aborts the run if any engine or setting
still names a database that does not end in `_test`.

What the isolation tests cover: the runtime role cannot bypass RLS; RLS is enabled, forced and has a
policy on every tenant table; any new table with a `tenant_id` must be registered (otherwise the
suite fails); a tenant-scoped session sees only its own rows, even when the query explicitly asks for
another tenant's; cross-tenant inserts, moves, updates and deletes are blocked; the tenant never
outlives its transaction on a reused pooled connection; concurrent requests for different tenants do
not mix.

One migration test (`downgrade` → `upgrade` round trip) is skipped when another database on the same
Postgres server still depends on the `app_runtime` role, because Postgres roles are cluster-wide.
It always runs in CI, which starts from a clean server.
