# ADR 0007: Signed demo sessions, rate limits and spend caps

## Status

Accepted (M8a).

## Context

The demo will be public, and the agent calls a paid model. Until now identity was a header any caller could
set per request (`X-Tenant-Id`), a support agent was whoever the request body said, and nothing limited how
much one visitor, or a script, could spend. Two risks follow: someone sees or does what they should not (any
employee reading a colleague's chat, anyone approving as a support agent), and someone burns the budget.

A real login is out of scope: the demo has fictitious people and the visitor picks who to be. What it needs is
for that choice to be made once and then *enforced by the server*, and for spending to be bounded.

## Decisions

**1. A signed session token, minted for a chosen person.** `POST /api/demo/session {tenant_id, employee_id}`
returns `base64url(payload).base64url(HMAC-SHA256)` carrying tenant, employee, a random session id and an
expiry (12 h). It is a dependency-free, one-algorithm cousin of a JWT (no `alg` to confuse). It proves "this
browser session chose to be this person", not who someone really is: anyone can mint a token for any
fictitious person. That is stated on the entry screen. What changes is that tenant, employee and role stop
being per-request claims.

**2. Two modes, one dependency.** `AUTH_MODE=signed` requires the token on every route except health, tenants,
the directory and session creation; tenant and employee come from it and `X-Tenant-Id` is ignored.
`AUTH_MODE=header` (default, local development and the test suite) keeps the old behaviour but honours a valid
token if one is sent, so the UI exercises the signed path in development too. `ENVIRONMENT=production`
refuses to start unless the mode is `signed` and the secret has 32+ characters.

**3. Authorization is enforced from the principal.** With a token: an employee sees and talks only in their own
conversations and sees only their own approvals and tickets (other people's conversations are 404, not 403, so
their existence is not confirmed); a support agent can read every conversation in the tenant but still only
talks in their own; the approver of an approval, the actor on escalations and the author of knowledge-base
writes are the caller, whatever the body says; the human queue and article writes are support-only. The
existing rules (support agent, not your own request) still run underneath.

**4. Spend is counted in Redis, in three scopes.** Micro-dollar integers per session, per IP per day and for
the whole demo per day. Chat cost, tool-time embeddings and knowledge-base search/write embeddings all count
(the knowledge tool charges the run, so the number stored on the run includes it too). A run is refused with
`429` and a code (`budget_exhausted_session|ip|day`) once any cap is spent; the check is before the run and the
recording after it, so one run can overshoot a cap by its own cost. Caps are settings (`0` turns one off).

**5. Rate limits are fixed windows**, also in Redis: messages per minute (per session and per IP), knowledge
search and writes per minute, session creation per hour per IP. `429` carries `Retry-After` and
`code: rate_limited`. The client IP is the socket address, or the last `X-Forwarded-For` hop (the one our
proxy added) only when `TRUST_FORWARDED_FOR` is set (behind Caddy), so a caller cannot pick its own IP
otherwise. (It was the first hop until the pre-deploy security review: spoofable behind any proxy that appends.)

**6. A sweeper does the housekeeping nobody else would**: runs stuck in `running` past 10 minutes are closed as
failed, unsigned approvals past their expiry are closed and the employee is told in the conversation, old
idempotency keys are dropped. It sweeps all tenants with the admin session (the runtime role cannot, on
purpose), runs as a background task guarded by a Redis lock, and never dies on an error.

**7. The UI** mints the session from the entry screen, sends the token, signs out and says so on a `401`, shows
limits in its own language, keeps a limited message as `NOT SENT`, and shows the remaining session budget in the
preferences panel (`GET /api/demo/budget`).

## Consequences

- A leaked token is valid until it expires (no revocation list). With fictitious data and a 12 h life that is
  accepted; rotating `DEMO_TOKEN_SECRET` invalidates all of them.
- Visitors behind one corporate NAT share the per-IP daily cap. It is the cheapest protection against one
  machine draining the budget; it can be raised or switched off.
- When the daily cap is spent the demo is read-only until midnight UTC. A replay mode with recorded runs is
  the planned answer (backlog), not part of this change.
- Header mode must never be exposed publicly; the production check exists to make that a startup error.
