# ADR 0008: Behaviour evals for the agent, and how models are compared

## Status

Accepted (M8b).

## Context

Everything up to M8a tests the *machinery* with a scripted model: the loop, the ledger, approvals, isolation,
limits. None of that says whether the real model behaves: does it open one ticket or three, does it claim a
password was reset when it was only requested, does it follow an instruction planted in an article? Those are
properties of a model plus a prompt, they change when either changes, and the only way to know is to run them.

The demo also has to pick a model. The choice is a trade between quality, latency and cost, and it should rest
on numbers from this product's own tasks, not on a leaderboard.

## Decisions

**1. Cases are conversations with checks, not prompts with expected answers.** A case is one fictitious
employee, one to three messages, and a list of checks (`backend/evals/cases.py`). Most checks read *facts*: which
tools were called, how many tickets / approvals / escalations exist afterwards, whether the audit log shows a
sensitive action ran. A few read the wording of a reply with a plain pattern (names the article, promises an
email, claims a reset happened). No model grades another model: that would add cost, a second source of
variance and a judge nobody has validated. The price is that a wording check can be fooled by an unusual
phrasing, so the unit tests pin each pattern against honest and dishonest examples, and a failure is read in
the report before it is blamed on the model. Two of the first run's eight failing runs were bugs in the checks.

**2. The real stack, throwaway data.** A run clones the demo companies into temporary tenants (employees, systems,
and the knowledge base embedded with the real embedder), plays every case with a *brand-new employee* so cases
cannot see each other's tickets, and deletes the tenants afterwards, also when the run crashes (`--cleanup`
removes leftovers from a killed run). The same `run_agent`, tools, Row Level Security and database as the API
are used; only the HTTP layer is skipped. Demo data is never touched.

**3. Repeat, because the model is not deterministic.** Each case runs `--repeat` times. The report shows runs
passed and *cases that passed every time*: a case that passes 1 of 2 is a finding about reliability that a
single run would hide.

**4. Spending is capped by the harness, not by good intentions.** `--max-usd` stops starting new runs once
reached (a run in flight finishes, so the final figure can exceed the cap by one run). The price table was checked
against OpenAI's own pricing page (backlog 10), and a model missing from it is refused, because its cost would
read as zero.

**5. The suite is offline-tested, live-run on demand.** The checks and the harness are covered by free tests with
a scripted model (a good run passes, an overclaiming run fails for the right reasons, the budget stops runs,
nothing is left behind). The live runs are not part of CI: they cost money and vary. Raw transcripts go to
`backend/evals/results/` (git-ignored); the numbers worth keeping are copied to [docs/evals.md](../evals.md).

**6. Findings are fixed where they belong.** A model that prints an internal id is first denied the id (the
escalation and article ids are no longer in what it sees), then told in the prompt; a wrong urgency is a prompt
rubric; and a wording bug is a check fix. The before/after numbers are in docs/evals.md.

**7. Retrieval has its own measurement.** `scripts.eval_retrieval` scores search alone (hit@1, hit@3, misses, false
accepts) over a gold set that now has paraphrases, typos, Spanish, undocumented questions and questions that belong
to another company, and reports them per kind at the configured threshold.

## Consequences

- A pass rate is a statement about *these* cases, with a small number of repeats: good enough to catch a model
  that is clearly worse or a prompt change that breaks a contract, not to rank two models that differ by a case.
- The suite checks what the prompt promises. Tone, brevity and whether an answer is *helpful* are not measured.
- Changing the prompt, a tool description or the model means re-running the suite; the cost of that (a few
  cents) is deliberately lower than the cost of finding out in the demo.
- Cases are plain Python, so a failure seen in the wild can become a regression case in a few lines.
