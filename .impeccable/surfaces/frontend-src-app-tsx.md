---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: []
---

# Triagent web app

Mode: Operate. The visitor completes a task inside the product (chat as an employee, decide as a support agent, inspect a run, manage help articles).

## Audience, task, constraints
- Evaluator opening a portfolio link, often on a phone, 2-5 minutes, no onboarding available.
- Two personas inside the demo: employee, support agent. Identity is chosen on an entry screen (demo, claimed).
- Must work equally well on a 390px phone and a desktop. English, with a switch to Spanish.
- Chosen memorable moment: watching the agent work live (real steps, real timings, sources, cost) during the 20-30 s a turn takes.
- Avoid: generic admin template, toy chatbot look, density that overwhelms a phone, style that obscures state.

## Signature interaction and motion grammar
The listing prints live: each agent step appears as a new ruled line with a short line-feed reveal (about 180 ms, ease-out), its duration bar growing to scale while the step runs. A small readout of elapsed time, tokens and cost ticks in the margin. Reduced motion: lines appear instantly, the bar is static. Everything else is state-only motion.

## Direction contract

THESIS: The agent's work is printed, not chatted: every step is a ruled line on a banded greenbar listing, and nothing is ever deleted, only stamped. Refuses the sidebar-plus-bubbles helpdesk template.

OWN-WORLD: Greenbar fanfold. Pale green bands (#E4F0DA) alternating with white paper, ink #161B26, ribbon-blue for human signatures, ribbon-red for void and failed stamps, amber only for awaiting. Workhorse sans for prose; monospace only in time, actor, milliseconds and cost columns; hairline-ruled columns; rubber-stamp states (APPROVED, REJECTED, VOID, FAILED) as outlined stamps. Dark scheme is a phosphor listing with near-black green bands.

STORY: A visitor chats as an employee, watches the listing print the agent's steps with time and cost, sees an unsigned approval line wait, switches to support, countersigns it, and sees the signed entry appear back in the employee's listing.

FIRST VIEWPORT: Entry screen: three ruled rows (company, one fictitious fact, "enter as"), a persona switch Employee / Support. In the app, desktop: slim conversation list, the listing in the centre with the composer docked at the bottom, a run-detail column on the right. Phone: one column, listing above, composer above a three-tab bottom bar per role (employee: Chat, Requests, Knowledge; support: Queue, Chats, Knowledge; runs are inspected from any listing line, so there is no Runs tab); the primary action is Send, reachable by thumb.

FORM: Greenbar audit listing, candidate 5 of 7 on my grounded list (1 flight progress strips, 2 trace waterfall viewer, 3 railway interlocking panel, 4 triage tracking board, 5 greenbar audit listing, 6 telephone switchboard, 7 lab notebook); assigned by the roll, seed key d07a11ca. Raises kept: rejected/expired/failed lines stay struck and stamped (ticket wallet); durations drawn to scale (labanotation); live readout ticks (specimen).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Unresolved decisions
- Exact faces and sizes (chosen during build under the tokens it produces).
- Whether the run-detail column becomes a bottom sheet on phones (expected: yes).
