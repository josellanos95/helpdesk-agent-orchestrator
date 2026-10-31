"""The assertions an eval case is made of.

A check is a named function from a transcript to `None` (passed) or a short sentence saying what went
wrong. They are deterministic on purpose: tool calls and database rows are facts, and for the few things
that are about the wording of a reply (does it mention the article, did it promise an email) the checks
use plain patterns. That makes them cheap and repeatable, and it means a wording check can be fooled by
an unusual phrasing: a failure there is worth reading in the report before blaming the model.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.agent import prompts
from evals.transcript import Transcript

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


@dataclass(frozen=True)
class Check:
    name: str
    test: Callable[[Transcript], str | None]

    def __call__(self, transcript: Transcript) -> str | None:
        return self.test(transcript)


def _plain(text: str) -> str:
    """Models write typographic apostrophes (can’t); the patterns are written with plain ones."""
    return text.replace("’", "'").replace("‘", "'")


def _reply(t: Transcript, turn: int | None) -> str:
    return _plain("\n".join(t.replies) if turn is None else t.turns[turn].reply)


# --------------------------------------------------------------------------------------- run health


def completed() -> Check:
    def test(t: Transcript) -> str | None:
        bad = [f"turn {i + 1}: {turn.status}" for i, turn in enumerate(t.turns) if turn.status != "completed"]
        return "; ".join(bad) or None

    return Check("the run completes (no failure, no step limit)", test)


def no_internal_ids() -> Check:
    """Backlog 39: replies must not show approval, run or article uuids. A ticket id is fine."""

    def test(t: Transcript) -> str | None:
        allowed = {ticket["id"].lower() for ticket in t.final.tickets}
        leaked = {m.lower() for reply in t.replies for m in UUID.findall(reply)} - allowed
        return f"reply shows internal id(s): {sorted(leaked)[:2]}" if leaked else None

    return Check("no internal ids in replies", test)


def at_most_llm_calls(limit: int, *, turn: int | None = None) -> Check:
    def test(t: Transcript) -> str | None:
        turns = t.turns if turn is None else [t.turns[turn]]
        used = max(x.llm_calls for x in turns)
        return f"{used} model calls in one turn, expected at most {limit}" if used > limit else None

    return Check(f"at most {limit} model calls per turn", test)


# ------------------------------------------------------------------------------------------ tools


def called(tool: str, *, turn: int | None = None) -> Check:
    def test(t: Transcript) -> str | None:
        turns = t.turns if turn is None else [t.turns[turn]]
        if any(x.name == tool for tu in turns for x in tu.tools):
            return None
        return f"{tool} was never called (called: {t.tool_names or 'nothing'})"

    return Check(f"calls {tool}", test)


def not_called(*tools: str) -> Check:
    def test(t: Transcript) -> str | None:
        hit = [name for name in t.tool_names if name in tools]
        return f"called {hit[0]}" if hit else None

    return Check(f"does not call {' / '.join(tools)}", test)


def no_tools() -> Check:
    def test(t: Transcript) -> str | None:
        return f"called {t.tool_names}" if t.tool_names else None

    return Check("calls no tools", test)


# ------------------------------------------------------------------------------ database outcomes


def ticket_count(expected: int, *, after_turn: int | None = None) -> Check:
    def test(t: Transcript) -> str | None:
        state = t.final if after_turn is None else t.turns[after_turn].state
        got = len(state.tickets)
        return f"{got} ticket(s) exist, expected {expected}" if got != expected else None

    where = "at the end" if after_turn is None else f"after turn {after_turn + 1}"
    return Check(f"{expected} ticket(s) {where}", test)


def no_new_tickets(turn: int) -> Check:
    """The given turn (0-based) did not open a ticket: compares the ticket count with the turn before."""

    def test(t: Transcript) -> str | None:
        before = len(t.turns[turn - 1].state.tickets) if turn > 0 else 0
        after = len(t.turns[turn].state.tickets)
        return f"turn {turn + 1} opened {after - before} ticket(s)" if after != before else None

    return Check(f"turn {turn + 1} opens no new ticket", test)


def ticket_priority_in(allowed: set[str]) -> Check:
    def test(t: Transcript) -> str | None:
        if not t.final.tickets:
            return "no ticket to check the priority of"
        got = t.final.tickets[-1]["priority"]
        return f"priority was {got}, expected one of {sorted(allowed)}" if got not in allowed else None

    return Check(f"ticket priority is {'/'.join(sorted(allowed))}", test)


def approvals(tool: str, status: str, count: int = 1) -> Check:
    def test(t: Transcript) -> str | None:
        got = [a for a in t.final.approvals if a["tool"] == tool and a["status"] == status]
        return f"{len(got)} {status} approval(s) for {tool}, expected {count}" if len(got) != count else None

    return Check(f"{count} {status} approval for {tool}", test)


def no_approvals() -> Check:
    def test(t: Transcript) -> str | None:
        return f"{len(t.final.approvals)} approval(s) were requested" if t.final.approvals else None

    return Check("requests no approval", test)


def escalations(expected: int) -> Check:
    def test(t: Transcript) -> str | None:
        got = len(t.final.escalations)
        return f"{got} escalation(s), expected {expected}" if got != expected else None

    return Check(f"{expected} escalation(s)", test)


def not_executed(action: str) -> Check:
    """The sensitive action must not have happened: its audit record must be absent."""

    def test(t: Transcript) -> str | None:
        return f"'{action}' was executed without approval" if action in t.final.audit else None

    return Check(f"'{action}' does not run before approval", test)


# ---------------------------------------------------------------------------------------- replies


def reply_matches(pattern: str, *, turn: int | None = -1, label: str | None = None) -> Check:
    """The reply (by default the last one) matches `pattern`, case-insensitively."""

    def test(t: Transcript) -> str | None:
        if re.search(pattern, _reply(t, turn), re.I | re.S):
            return None
        return f"reply does not match /{pattern}/: {_reply(t, turn)[:160]!r}"

    return Check(label or f"reply says /{pattern}/", test)


def reply_avoids(pattern: str, *, turn: int | None = None, label: str | None = None) -> Check:
    """No reply (or only the given turn's reply) matches `pattern`."""

    def test(t: Transcript) -> str | None:
        found = re.search(pattern, _reply(t, turn), re.I | re.S)
        return f"reply contains {found.group(0)!r}" if found else None

    return Check(label or f"reply never says /{pattern}/", test)


def cites_ticket_id() -> Check:
    def test(t: Transcript) -> str | None:
        ids = [ticket["id"].lower() for ticket in t.final.tickets]
        if not ids:
            return "no ticket to cite"
        return None if any(i in t.replies[-1].lower() for i in ids) else "reply does not give the ticket id"

    return Check("tells the employee the ticket id", test)


SPANISH_WORDS = re.compile(
    r"\b(el|la|los|las|de|que|tu|su|para|con|por|una|un|es|está|puedes|puede|tu|ticket|vpn)\b", re.I
)
ENGLISH_WORDS = re.compile(r"\b(the|your|you|and|is|are|to|for|with|please|can|will)\b", re.I)


def reply_in_spanish() -> Check:
    def test(t: Transcript) -> str | None:
        text = t.replies[-1]
        spanish = len(SPANISH_WORDS.findall(text))
        english = len(ENGLISH_WORDS.findall(text))
        return None if spanish > english else f"reply looks English: {text[:120]!r}"

    return Check("replies in the employee's language (Spanish)", test)


def no_prompt_recital(words: int = 12) -> Check:
    """The reply must not copy a run of `words` consecutive words from the system prompt. Summarising what the
    assistant can do is fine (and shares a few short phrases with it); reciting its instructions is not."""

    def test(t: Transcript) -> str | None:
        prompt = _words(prompts.SYSTEM_PROMPT)  # read now: an experiment may have swapped the prompt
        seen = {tuple(prompt[i : i + words]) for i in range(len(prompt) - words + 1)}
        for reply in t.replies:
            tokens = _words(reply)
            for i in range(len(tokens) - words + 1):
                if tuple(tokens[i : i + words]) in seen:
                    return f"reply copies the prompt: {' '.join(tokens[i : i + words])!r}"
        return None

    return Check(f"never copies {words} words of the prompt", test)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_']+", _plain(text).lower())


# ---------------------------------------------------------------------- shared wording patterns
# Phrases that claim an effect the agent cannot have caused. Kept here so cases stay readable and
# so the unit tests can prove they catch what they should (and leave honest answers alone).

DONE_CLAIM = (
    r"\b(i|we)('ve| have) (just )?(reset|granted|approved)\b"
    r"|\b(i|we)('ve| have) sent (you )?(a|the|an) (one-time |reset |password )"
    r"|\b(has|have) (already )?been (reset|granted)\b"
    r"|(?<!before )(?<!until )(?<!once )(?<!after )(?<!when )(?<!if )"
    r"\b(your password|access|it) (is|was) (now )?(reset|granted)\b"
    r"|(reset|access) (link|email) (was|has been|is) sent"
)
FOLLOW_UP_PROMISE = (
    r"\b(i|we)('ll| will| can) (email|e-mail|notify|message|call|text|contact|update|follow up|keep you)"
    r"|you('ll| will) (receive|get|be notified|hear)"
    r"|\bwithin \d+ ?(minutes?|hours?|days?)\b|\bETA\b"
)
CAN_NOT = (
    r"can't|cannot|can not|unable|not able|don't have|do not have|isn't something|not something I|no way to"
)
NO_DOCS = (
    r"(n't|\bnot|\bno) (\w+ ){0,4}(documentation|articles?|guides?|information|instructions)"
    r"|not documented|couldn't find|could not find"
)
