# ADR 0002: Agent loop — one tenant-scoped transaction, SAVEPOINT per tool, trace as data

## Status

Accepted (M3). One consequence is a known limitation to be revisited in M4 (see "Trade-offs").

## Context

The agent answers one user message by looping: call the model, run the tools it asked for, feed the
results back, repeat until it answers. It has to stay inside the tenant boundary from ADR 0001, survive
tools and models that fail, and leave enough behind to debug any run afterwards.

## Decisions

**1. Everything for one user message runs in a single tenant-scoped session.** The loop, the
tools, the messages and the trace all go through the RLS-enforced `app_runtime` connection. A tool has no
way to reach another tenant even if it is buggy or a prompt injection aims it there.

**2. Tools never receive identity from the model.** `tenant_id`, `employee_id` and `conversation_id`
live in a `ToolContext` built from the authenticated request. A unit test fails if any tool schema grows
an argument with one of those names.

**3. Each tool runs inside a SAVEPOINT** (`session.begin_nested()`). A tool that raises, or that makes
the database reject a statement, rolls back only its own work. Without it, a failed SQL statement aborts
the whole transaction and the run — messages, trace and all — is lost with it. A mutation test (remove the
SAVEPOINT) proves the test suite catches this.

**4. Tool failures are data for the model, not exceptions.** Unknown tool, malformed JSON, schema
violations and runtime errors all come back as a tool result so the model can recover or tell the user.
Runtime errors are replaced by a generic message for the model; the real exception text is kept in the
trace only, so internals do not enter the prompt.

**5. Hard stop at `max_steps`** (default 6): the run ends with status `max_steps` and a fixed apology
rather than looping on a confused model and spending tokens.

**6. A model/provider failure still produces a stored run and a reply.** The run is marked `failed` with
the error, the user gets a fixed message, and the HTTP call returns 200 with `run.status = "failed"`. The
alternative — letting the exception propagate — would roll back the transaction and erase the evidence.

**7. The trace is ordinary tenant-scoped data** (`agent_runs`, `agent_steps`): per step the kind, name,
input, output, latency, tokens and error; per run the totals and cost. Cost is computed from a price table
in code. Those prices came from third-party trackers and must be verified against OpenAI's page.

**8. `messages.seq`, an identity column, defines message order.** `created_at` defaults to `now()`, which in
Postgres is the *transaction start* time, so every message written during one request has the same
timestamp. Ordering by it would be nondeterministic. (A test asserts the timestamps really do tie.)

## Trade-offs and known limitations

- **A database transaction stays open while the model thinks.** The session is opened before the loop and
  committed after it, so each request holds one connection for the full duration of every LLM call —
  seconds, sometimes tens of seconds. With a small pool that caps concurrency. Splitting the run into short
  transactions per step is the fix, and it fits M4, where idempotent execution needs per-step commit points
  anyway.
- **`create_ticket` is not idempotent yet.** If the model calls it twice for the same problem it creates two
  tickets. The prompt discourages it; M4 makes it structurally impossible.
- **Tenant identity is still the `X-Tenant-Id` header.** RLS stops query bugs, not impersonation. Real
  demo authentication lands in M8.
- **Prompt-injection resistance so far is a system-prompt instruction plus tool-level isolation.** The
  adversarial eval cases are M8.
