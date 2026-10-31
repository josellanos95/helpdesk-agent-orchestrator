# Security review (before the public deploy)

A review of the repository and the application before it is hosted (M9), done on 2026-10-31 at commit
`056f915` plus the fixes listed below. It covers what is in the public repo, the dependencies, and the code
paths a public visitor can reach in `AUTH_MODE=signed`. It is a self-review, not a penetration test.

## Method

- **Secrets and personal data:** every commit on every branch searched for OpenAI, GitHub and AWS key formats
  and private keys; every tracked file for passwords, tokens, personal paths, addresses and IPs; the list of
  files that were ever tracked, to catch a committed `.env`.
- **Dependencies:** `pip-audit` on `requirements.txt` and `requirements-dev.txt`, `npm audit` with and without
  dev dependencies.
- **Static analysis:** `bandit` (medium and high), plus a search for raw SQL and HTML sinks.
- **Reading the code** that decides who a caller is and what they may touch: the signed token, the principal
  and actor checks on every route, Row Level Security and the database role, CORS, the client IP behind a
  proxy, error handling, the Dockerfile, the compose file and CI.

## Fixed in this review

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | Starlette 0.41.3 (through FastAPI 0.115.6) had 7 published advisories, among them an unvalidated `Host` header rebuilding `request.url` and form parsing without limits. | Medium | FastAPI 0.162.0, Starlette pinned to 1.10.0. `pip-audit`: no known vulnerabilities. 399 tests pass. |
| 2 | Behind a proxy the client IP was the *first* `X-Forwarded-For` hop. Caddy replaces the header by default, but any proxy that appends would let a caller choose a new IP per request and walk past the per-IP rate limits and budget. | Medium | The last hop (the one our proxy wrote) is used. Test added. |
| 3 | The run inspector showed raw exception text. An OpenAI authentication error includes a masked key, a database error can include SQL. | Low | In production visitors see only the exception type; the database keeps the full text. Test added. |
| 4 | Production would start with `APP_DB_PASSWORD=app_dev_password`, which is in this repo. | Medium | `ENVIRONMENT=production` refuses to start with it. Test added. |
| 5 | The API container ran as root. | Low | Runs as an unprivileged `app` user (uid 10001); image built and checked. |
| 6 | The development compose file published Postgres (password `helpdesk`) and Redis (no password) on every network interface. | Low (local) | Bound to `127.0.0.1`. |
| 7 | CI's token had the repository's default permissions. | Low | `permissions: contents: read`. |
| 8 | CORS allowed credentials, which nothing uses (the token travels in `Authorization`). | Info | `allow_credentials=False`. |
| 9 | Vite, `nanoid` and `source-map-js` advisories (development tooling only, not in the built bundle). | Low | `npm audit fix`: 0 vulnerabilities. |

Each new test was checked by breaking the fix on purpose and watching the test fail.

## Open: decide before hosting

**A. Visitors share the demo's state (high, only if hosted).** Every visitor chooses from the same seven people,
and anyone can choose a support agent. In the hosted demo that means:

- a visitor who picks a support agent can create, edit or **delete** knowledge-base articles for every later
  visitor of that company (the agent treats passages as data, and an eval case checks a planted instruction is
  ignored, but defacement and deleted articles would still show);
- two visitors who pick the same employee see each other's conversations, and a support agent sees every
  conversation in the company, so anything a visitor types is visible to strangers.

Options, from strongest to cheapest: give each demo session its own copy of a company (the eval harness already
clones companies and deletes them afterwards); reset the demo data on a schedule and make knowledge-base writes
visible only to the session that made them; at the very least, a nightly reset plus a line on the entry screen
saying conversations are visible to other visitors. To be decided in M9.

**B. Security headers.** The frontend (Vercel) and the API (Caddy) should send `Content-Security-Policy`,
`frame-ancestors`/`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` and HSTS. Part of the M9
configuration.

**C. Spend.** The app's daily cap (`DAILY_BUDGET_USD`, default $1) bounds what visitors can spend; the per-IP cap
can be split across many addresses, the daily one cannot. The OpenAI key for the demo should be a separate
project key with a monthly hard limit, so a bug in the caps still cannot cost more than that limit.

**D. Repository settings (owner).** Secret scanning and push protection are on. Not yet: branch protection on
`main` requiring CI, and Dependabot security updates.

**E. Accepted.** `pytest` 8.3.4 has an advisory; it is a test dependency, not in the image. `/docs` and
`/openapi.json` stay public: the API is meant to be read. The demo token lives in `localStorage`; with no HTML
rendering of model or article text there is no script to steal it, and it only grants a fictitious persona.

## Checked and found sound

- **No secret in the history.** No key of any known format in any commit on any branch; `.env` was never
  tracked, only the two `.env.example` files with placeholders.
- **Tenant isolation is enforced by the database**, not the code: Row Level Security on every tenant table,
  forced, with a runtime role that has neither `SUPERUSER` nor `BYPASSRLS` (ADR 0001), covered by tests.
- **Identity comes from the signed token, never the request body** in signed mode: approver, escalation actor and
  article author are the caller; other employees' conversations answer 404. HMAC-SHA256 with a constant-time
  comparison, one algorithm, expiry checked (ADR 0007).
- **The model cannot choose who it acts for:** no tool takes a tenant, employee or conversation id; sensitive
  actions only create approvals; a failing tool tells the model a generic sentence.
- **No HTML injection path:** model and article text are rendered as React text nodes, never as HTML.
- **Inputs are bounded** (message 4,000 characters, article body, search query, note), SQL is parameterised
  (`bandit` reports nothing at medium or high), and the production bundle has no known vulnerable dependency.
- **Prompt injection** is covered by four eval cases (pasted orders, an order planted in an article, reciting
  the prompt, a pasted password), passing in every run of the chosen model ([evals](evals.md)).
