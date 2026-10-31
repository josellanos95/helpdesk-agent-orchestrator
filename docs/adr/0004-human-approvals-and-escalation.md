# ADR 0004: Human approvals for sensitive actions, and the escalation queue

## Status

Accepted (M5).

## Context

An agent that can reset passwords or grant access must not do so on its own say-so, however good the
model is: its input is untrusted text, and a persuasive message or an injected instruction is enough to
talk it into an action. The safe design is not a better prompt but a boundary the model cannot cross: for
some tools it can only *ask*, and a person with the right role decides.

## Decisions

**1. Approval is a property of the tool, not of the prompt.** `Tool.requires_approval` (set on
`reset_password` and `grant_system_access`) makes the runner park the call instead of executing it. A unit
test pins the exact set of tools that need approval, so adding a tool forces someone to decide.

**2. Nothing runs while the request is pending.** The call is validated, normalised and stored as an
`Approval` row. The model gets `pending_approval` and is told not to claim the action happened. Requests
are deduplicated: the same `tool_call_id` returns the same approval, and the same tool with the same
arguments while one is pending reuses it (`already_pending`), because models repeat themselves.

**3. Approving executes through the tool ledger with the original `tool_call_id`.** That makes the action
exactly-once however the decision arrives (ADR 0003). On top of that the approval row is read with
`SELECT ... FOR UPDATE`, so concurrent decisions serialise; deciding the same way again replays the result,
deciding the opposite way is a 409.

**4. Who may decide is enforced in the service**, not in the UI: the approver must be a support agent of the
same tenant (RLS makes other tenants' employees invisible, so they are indistinguishable from nobody), and
nobody may decide their own request, which includes support agents asking for something for themselves.

**5. Requests expire after 24 hours** and can no longer be approved.

**6. The outcome is told to the employee in the conversation** with a deterministic message, not a model
call: no cost, no hallucination, trivially testable. The next turn's model sees it in the history.
Because that message is appended to the conversation, a decision takes the **conversation lock**; otherwise
it could land between an assistant tool call and its result and make the history invalid for the model API.
A busy conversation gets 409 and the decision is retried.

**7. Every sensitive step is in an append-only `audit_log`**: the request, the decision with who made it and
why, and the action itself. The runtime database role has no `UPDATE` or `DELETE` on it, so neither a bug nor
an injected instruction can edit history (a test proves it).

**8. Escalation is its own, smaller thing.** `escalate_to_human` only works on the employee's *own* ticket
(checked in the tool, not just by RLS) and is idempotent per ticket. The queue (`pending` -> `acknowledged`
-> `resolved`) is worked by support agents and moves the ticket's status.

## Trade-offs and known limits

- **The approver is claimed in the request body** until authentication exists (M8). The role and
  self-approval checks are real, but today anyone calling the API for a tenant can name any of its agents.
- **A double-click over HTTP gets one 200 and some 409s** (the losers hit the conversation lock). A retry
  gets the replayed 200. The UI should retry on 409.
- **Expiry is lazy.** An expired request stays `pending` until someone tries to decide it, and the employee
  is not told. A background job would close and announce them (M8).
- **`reset_password` and `grant_system_access` are simulated**: they write an audit record. Real identity
  verification of the *requester* is delegated to the human approver.
- **Escalations have no assignee**; who acknowledged one is only in the audit log.
