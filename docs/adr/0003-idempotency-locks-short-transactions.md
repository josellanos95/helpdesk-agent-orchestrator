# ADR 0003: Short transactions, a tool ledger, a conversation lock and idempotency keys

## Status

Accepted (M4). Supersedes the "one transaction for the whole run" decision in ADR 0002.

## Context

Live testing in M3 and a review of the failure modes showed four ways the agent could misbehave under
ordinary conditions, none of which needs an attacker:

1. A request held a database connection for the whole run, including every model call (seconds each).
2. A client that timed out and resent its message ran the agent twice, and could open two tickets.
3. Two messages sent quickly to the same conversation ran concurrently and interleaved their messages.
4. A tool call replayed for any reason (a retry, and from M5 an approval clicked twice) would execute again.

## Decisions

**1. A transaction per step, never across a model call.** The run is a sequence of short tenant-scoped
transactions (`tenant_session`): create the run; then, per step, read the history, *close the transaction*,
call the model, and open a new one to store the response, run the tool calls and store their results. A test
asks `pg_stat_activity` while the model is "thinking" and requires zero open transactions (plus a test that
the probe does detect one, so the first cannot pass vacuously). Everything still goes through Row Level
Security, because every transaction is a tenant session.

A crash now leaves every finished step committed instead of losing the run. An unexpected exception marks
the run `failed` before it propagates.

**2. A tool ledger makes each call run at most once.** `tool_executions` has a unique key
`(tenant, conversation, tool_call_id)`. `execute_once` claims it with `INSERT ... ON CONFLICT DO NOTHING`,
runs the tool inside a SAVEPOINT and stores the result, all in the step's transaction:
- a replay returns the stored result (success or failure) and does not touch the world again
- concurrent attempts serialise on the unique index; the loser waits and then reads the winner's row
- a rollback removes the claim together with the tool's effects, so there is no "claimed but never ran"

**3. One run per conversation, enforced by a Redis lock.** `SET NX PX` to acquire; release through a Lua
script that deletes only if the stored token is still ours, so a run whose lock expired cannot free the lock
of the run that replaced it. The TTL is short (120 s) and renewed before every model call; if the lock is
found lost the run stops with `LockLost` and is marked failed instead of racing the new owner. A second
message gets HTTP 409 and is never stored. If Redis is down the request gets 503: the lock fails closed.

**4. `Idempotency-Key` for retried requests.** Same key and same body replays the stored response with
`Idempotent-Replay: true`; same key with a different body or conversation is 422; the same key while the
first request is running is 409. A run that ends `failed` (provider outage) *releases* the key, because
replaying an outage forever would make retrying impossible. A claim still `in_progress` after 5 minutes is
taken over with a compare-and-set, since its owner must have died.

**5. The model call is bounded.** The OpenAI client uses a 45 s timeout and one retry (worst case 90 s),
below the 120 s lock. The SDK default of 10 minutes could let a hung call outlive its own lock.

## Trade-offs and what this does not solve

- **The ledger covers repeats of the same `tool_call_id`.** If the model asks for the same action twice
  with two different ids, both run. That is a behaviour problem for the prompt and the M8 evals (there is an
  "exactly one ticket" case to write), not something an id-based ledger can see.
- **Idempotency keys never expire** and the table grows. Cleanup is M8.
- **Runs left `running` by a hard process kill** (no exception handler runs) stay that way. A reaper that
  closes runs older than the lock TTL is M8.
- **The lock is not a fencing token.** A run that loses the lock between two heartbeats can still finish
  the step it is in. The window is one step, and the ledger and the per-step transactions bound the damage.
- **A single Redis instance** is assumed. That is fine for this project; a real multi-region deployment
  would need something stronger than a TTL lock.
