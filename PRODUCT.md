# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Two audiences share one interface.

- **The evaluator (primary, confirmed).** A recruiter, hiring manager or engineer who opens a link from the owner's portfolio, often on a phone, and spends two to five minutes. They are judging an AI-engineering portfolio: they must understand what the agent does, see that it is safe, and trust that it is real, without anyone explaining it.
- **The two roles they play inside the demo.** An *employee* of a fictitious company who asks the agent for IT help, and a *support agent* of that company who reviews what the agent could not or must not do alone (approvals, escalations, the knowledge base).

Usable equally well on a phone and on a desktop; neither is a degraded version of the other.

## Product Purpose
Triagent is a multi-tenant AI helpdesk agent. Employees ask for IT help in chat. The agent answers from the company's own documentation, checks system status, files tickets, and asks a human before any sensitive action (password reset, access grant). Everything it does is recorded and inspectable. Success for the interface: within a couple of minutes a visitor has had a real conversation, watched the agent work step by step, seen a sensitive request wait for a human, and approved it.

## Positioning
The agent is built to fail safely, and the interface shows it: tenant isolation by the database, human approval for sensitive actions executed exactly once, an append-only audit log, a full trace of every run (each model call and tool call with latency, tokens and cost). A neighbouring chatbot demo cannot truthfully show any of those.

## Operating Context
- Three fictitious companies (Acme, Globex, Initech) with their own employees, systems, help articles and, deliberately, different answers to the same question (each has its own VPN client).
- A full agent turn takes 20-30 seconds with the current model, so the interface must make waiting legible (live steps), not hide it.
- Sensitive requests are decided by a different person from the requester; the demo lets the visitor switch persona to do both halves.
- Until real authentication exists (planned) identity is chosen by the visitor on an entry screen and sent as headers; the interface must say it is a demo.

## Capabilities and Constraints
- Backend API already exists: tenants, employees, conversations and messages (with `Idempotency-Key`), run traces, approvals (list, decide), escalations (list, acknowledge, resolve), knowledge-base articles (list, read, create, replace, delete, search). Some read endpoints for the UI are still to be added.
- A message gets HTTP 409 while another message of the same conversation is being processed; a decision gets 409 when the conversation is busy. The UI must retry or explain.
- A failed run (provider outage) still returns a reply and a `failed` status; it must read as an error state.
- Frontend stack is already chosen by the codebase: Vite, React 19, TypeScript, Tailwind CSS v4, oxlint.
- Interface language: English by default with a switch to Spanish. The agent's replies follow the language of whoever writes.
- No invented claims: costs, latencies and counts shown must come from the traces.

## Brand Commitments
- Name: Triagent.
- Owner: Jose Llanos (portfolio project). Deliberately honest in tone about limits (demo identity, simulated actions).

## Evidence on Hand
- Real traces, costs and latencies from live runs with gpt-5-mini (about 20-30 s per turn, fractions of a cent per turn).
- A measured retrieval result on the demo knowledge base (hit@1 100% on 20 answerable questions, 0 of 6 noise answers); small set, to be described as a calibration.
- Demo companies and articles are fictitious and must stay labelled as such.
- No screenshots, logos, testimonials or user metrics exist. None may be fabricated.

## Product Principles
1. **Show the work.** The agent's steps, sources, costs and failures are first-class content, not developer-only detail.
2. **Safety is visible.** The human-approval boundary and tenant separation are things a visitor sees happen, not claims in a README.
3. **Honest about being a demo.** Simulated actions, claimed identities and fictitious data are labelled where a visitor could mistake them.
4. **One product, any screen.** The phone is a first-class target; every flow must be completable with one thumb.
5. **Waiting is a feature to design.** A 20-30 second turn needs live, truthful progress.

## Accessibility & Inclusion
Keyboard and screen-reader usable; visible focus; touch targets suitable for thumbs; respects reduced motion and system colour scheme; status never conveyed by colour alone.
