# ADR 0006: Web UI as a live audit listing

## Status

Accepted (M7).

## Context

The backend can do things worth seeing: it calls tools, asks a human before anything sensitive, searches a
per-tenant knowledge base, and records everything. A recruiter or engineer opening the demo on a phone has two
to five minutes and no onboarding. A chat bubble UI hides all of that; a generic admin template buries it. The
screen has to make "the agent did this, it took this long, a human signed that" the thing you see, and it has to
work equally on a 390 px phone and a desktop.

## Decisions

**1. The conversation is printed, not chatted.** Every step is a ruled line in a banded "greenbar" listing:
`time | actor | content | duration bar + tokens`. User message, model decision, tool call, reply, run totals and
a human signature are all lines of the same kind. Monospace is used only for time, actor, milliseconds and cost
and for stamps; everything that is read is sans. Rejected, expired and failed lines stay on the page, struck
and stamped (nothing is deleted, only stamped), which mirrors the append-only audit log behind it.

**2. The listing is built from stored facts, in one pure function.** `lib/lines.ts` maps messages, runs/steps and
approvals to lines. For that, `messages` gained `run_id` and `step_index` (migration `f2c71d9a30b5`), so each
assistant and tool line sits next to its real latency and tokens. The function is unit-tested; the components
only draw it.

**3. Live work by polling, not streaming.** Steps are committed one by one (ADR 0003), so while a `POST` is in
flight the UI polls `GET /conversations/{id}/messages` and `/runs` about once a second and prints each step as it
appears, with an elapsed-time/tokens readout on a live line. Cost is only known when the run ends and the UI says
so. Server-sent events would remove the poll but need a new transport and a way to resume; for a turn of 10 to
30 s this was not worth it yet.

**4. Sending is honest about failure.** One `Idempotency-Key` per intent. `409` (conversation busy, or the same
request still running) waits and retries with the same key, and says so on screen; a lost answer becomes a
`NOT SENT` line that can be resent without running the agent twice; a run that failed on the provider side
(HTTP 200, `status: failed`) is a `FAILED` stamp with a retry. This closes backlog items 11, 21 and 22.

**5. Roles are screens, not permissions.** The entry screen asks for a company and a person, as employee or as
support agent. Employees get Chat, Requests, Knowledge; support gets Queue (approvals and escalations), Chats
(read-only view of any conversation) and Knowledge (write). The identity is claimed, not authenticated, and the
entry screen says so; the backend rules (support agent, not your own request) hold regardless. Real demo
authentication is M8.

**6. One layout, container-aware.** Phone: one column, bottom tab bar, run inspector as a bottom sheet
(`<dialog>`). Desktop: top bar with tabs, conversation list, listing, inspector column (width thresholds
800 / 1100 / 1360 px). The listing switches between its four-column and stacked form by its own width (container
query), not the viewport's. Light and dark themes (dark is a phosphor listing) follow the system by default and
can be toggled.

**7. Stack.** Vite, React 19, TypeScript, Tailwind v4 (tokens as CSS variables), React Router, TanStack Query,
Vitest + Testing Library. UI text is English with a Spanish switch; only the interface is translated (agent
replies and article texts stay as written), and a test enforces identical keys and placeholders.

**8. Small backend additions for the UI**, all read-only: conversation list with preview and pending-approval
count, `GET /conversations/{id}/runs`, ticket list, and `conversation_id` / `requested_by` filters on approvals.

## Consequences

- A turn still takes 10 to 30 s; the live line makes the wait informative, it does not shorten it (backlog 7).
- Polling means a few requests per second per open conversation while it runs. Fine for a demo, not for scale.
- The claimed identity is the weakest part of the demo and is on the M8 list.
- Because the listing is derived from stored data, a conversation looks the same live and when reopened.
