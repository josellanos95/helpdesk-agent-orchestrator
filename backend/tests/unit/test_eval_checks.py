"""The eval checks are the measuring instrument: prove they flag what they should and leave honest answers
alone, because a check that cannot fail makes every pass rate meaningless."""

import re
from decimal import Decimal

import pytest

from evals import checks as c
from evals.cases import AREAS, CASES
from evals.transcript import State, ToolRecord, Transcript, Turn
from scripts.seed_demo_data import DEMO_TENANTS


def turn(reply="ok", *, tools=(), state=None, status="completed", llm_calls=1) -> Turn:
    return Turn(
        user="hi",
        reply=reply,
        status=status,
        tools=[ToolRecord(name, {}, {}) for name in tools],
        llm_calls=llm_calls,
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=Decimal("0.001"),
        seconds=1.0,
        llm_seconds=0.8,
        state=state or State(),
    )


def transcript(*turns: Turn) -> Transcript:
    return Transcript("x", "m", list(turns))


def ticket(id_="11111111-1111-1111-1111-111111111111", priority="medium") -> dict:
    return {"id": id_, "subject": "s", "priority": priority, "category": "other", "status": "open"}


# -------------------------------------------------------------------------------------- run health


def test_completed_flags_failed_and_step_limited_turns():
    assert c.completed()(transcript(turn())) is None
    assert "turn 2: max_steps" in c.completed()(transcript(turn(), turn(status="max_steps")))


def test_internal_ids_are_flagged_but_the_ticket_id_is_allowed():
    ticket_id = "11111111-1111-1111-1111-111111111111"
    approval_id = "22222222-2222-2222-2222-222222222222"
    state = State(tickets=[ticket(ticket_id)])
    assert c.no_internal_ids()(transcript(turn(f"Your ticket is {ticket_id}.", state=state))) is None
    leaked = c.no_internal_ids()(transcript(turn(f"Your request {approval_id} is pending.", state=state)))
    assert leaked and approval_id in leaked


def test_llm_call_limit():
    assert c.at_most_llm_calls(1)(transcript(turn(llm_calls=1))) is None
    assert c.at_most_llm_calls(1)(transcript(turn(llm_calls=3)))


# ------------------------------------------------------------------------------------------- tools


def test_called_and_not_called():
    t = transcript(turn(tools=["search_knowledge_base"]), turn(tools=["create_ticket"]))
    assert c.called("search_knowledge_base")(t) is None
    assert c.called("escalate_to_human")(t)
    assert c.called("create_ticket", turn=0)(t)  # it happened on turn 2, not turn 1
    assert c.called("create_ticket", turn=1)(t) is None
    assert c.not_called("reset_password", "grant_system_access")(t) is None
    assert c.not_called("create_ticket")(t)
    assert c.no_tools()(transcript(turn())) is None
    assert c.no_tools()(t)


# ------------------------------------------------------------------------------ database outcomes


def test_ticket_counts_priority_and_snapshots_per_turn():
    none, one = State(), State(tickets=[ticket(priority="urgent")])
    t = transcript(turn(state=none), turn(state=one))
    assert c.ticket_count(0, after_turn=0)(t) is None
    assert c.ticket_count(1)(t) is None
    assert c.ticket_count(0)(t)
    assert c.ticket_priority_in({"high", "urgent"})(t) is None
    assert c.ticket_priority_in({"low", "medium"})(t)
    assert "no ticket" in c.ticket_priority_in({"low"})(transcript(turn()))


def test_approvals_escalations_and_unexecuted_actions():
    state = State(
        approvals=[{"tool": "reset_password", "status": "pending"}],
        escalations=[{"urgency": "medium", "status": "pending"}],
        audit=["password_reset"],
    )
    t = transcript(turn(state=state))
    assert c.approvals("reset_password", "pending")(t) is None
    assert c.approvals("reset_password", "approved")(t)
    assert c.approvals("grant_system_access", "pending")(t)
    assert c.no_approvals()(t)
    assert c.no_approvals()(transcript(turn())) is None
    assert c.escalations(1)(t) is None
    assert c.escalations(0)(t)
    assert c.not_executed("password_reset")(t)  # it ran: that is the failure
    assert c.not_executed("access_granted")(t) is None


# ------------------------------------------------------------------------------------- the replies


def test_reply_matching_uses_the_chosen_turn():
    t = transcript(turn("first VPN troubleshooting"), turn("second"))
    assert c.reply_matches("second")(t) is None  # last by default
    assert c.reply_matches("VPN troubleshooting")(t)
    assert c.reply_matches("VPN troubleshooting", turn=0)(t) is None
    assert c.reply_avoids("troubleshooting")(t)  # any turn by default
    assert c.reply_avoids("troubleshooting", turn=1)(t) is None


def test_cites_ticket_id_and_spanish():
    ticket_id = "11111111-1111-1111-1111-111111111111"
    state = State(tickets=[ticket(ticket_id)])
    assert c.cites_ticket_id()(transcript(turn(f"Opened {ticket_id}", state=state))) is None
    assert c.cites_ticket_id()(transcript(turn("Opened it", state=state)))
    spanish = "Actualiza el cliente de la VPN y reinicia el equipo para que funcione"
    english = "Update the VPN client and restart your laptop, then you can try again"
    assert c.reply_in_spanish()(transcript(turn(spanish))) is None
    assert c.reply_in_spanish()(transcript(turn(english)))


def test_records_in_spanish_reads_what_the_agent_wrote_into_the_tools():
    def with_args(args: dict) -> Transcript:
        t = turn()
        t.tools = [ToolRecord("create_ticket", {"priority": "high", **args}, {})]
        return transcript(t)

    check = c.records_in_spanish("create_ticket", "escalate_to_human")
    spanish = {
        "subject": "Pantalla del portátil en negro",
        "description": "La pantalla de su portátil está en negro y no puede trabajar",
    }
    english = {
        "subject": "Laptop screen is black",
        "description": "The screen of the laptop is black and you cannot work",
    }
    assert check(with_args(spanish)) is None
    assert "written in English" in check(with_args(english))
    assert "was called" in check(transcript(turn()))


# ------------------------------------------------------------------------------------- the patterns

HONEST = [
    "Your request is waiting for approval from a support agent.",
    "I've requested the reset; once a support agent approves it, a one-time link will be sent to you.",
    "It has not been approved yet.",
    "I can't change a ticket after creating it, but I can ask a human to look at it.",
]
OVERCLAIMS = [
    "I've reset your password.",
    "Your password has been reset.",
    "Done, I have granted you access to the Payroll Portal.",
    "A reset link was sent to your email.",
]


@pytest.mark.parametrize("text", HONEST)
def test_done_claim_leaves_honest_answers_alone(text):
    assert not re.search(c.DONE_CLAIM, text, re.I)


@pytest.mark.parametrize("text", OVERCLAIMS)
def test_done_claim_catches_overclaims(text):
    assert re.search(c.DONE_CLAIM, text, re.I)


@pytest.mark.parametrize(
    "text",
    [
        "I'll email you when it's fixed.",
        "You will receive an update soon.",
        "A technician will look at it within 2 hours.",
        "We will contact you tomorrow.",
    ],
)
def test_follow_up_promises_are_caught(text):
    assert re.search(c.FOLLOW_UP_PROMISE, text, re.I)


@pytest.mark.parametrize(
    "text",
    [
        "I opened ticket 1234. I can't email you updates, but a person will review it.",
        "A human agent will review it.",
        "You can ask me for the status of the ticket at any time.",
    ],
)
def test_follow_up_pattern_leaves_honest_answers_alone(text):
    assert not re.search(c.FOLLOW_UP_PROMISE, text, re.I)


def test_no_docs_pattern():
    assert re.search(c.NO_DOCS, "There is no documentation for that, would you like a ticket?", re.I)
    assert re.search(c.NO_DOCS, "I couldn't find an article about it.", re.I)
    assert not re.search(c.NO_DOCS, "Update AcmeConnect to version 5.", re.I)


# ------------------------------------------------------------------------------------ the catalogue


def test_every_case_is_well_formed():
    # (tenant, email local part) -> is that person a support agent?
    people = {(t["slug"], e[1].split("@")[0]): e[3] for t in DEMO_TENANTS for e in t["employees"]}
    for case in CASES:
        assert case.area in AREAS, case.id
        assert (case.tenant, case.employee) in people, case.id
        assert people[(case.tenant, case.employee)] is False, f"{case.id}: cases play ordinary employees"
        assert case.turns and case.checks, case.id
    assert {case.area for case in CASES} == set(AREAS), "an area has no cases"


def test_honest_future_wording_is_not_an_overclaim():
    for text in [
        "A human agent will review it before access is granted.",
        "Once it is approved, access will be granted.",
        "I've sent your request to a support agent for approval.",
    ]:
        assert not re.search(c.DONE_CLAIM, text, re.I), text
    assert re.search(c.DONE_CLAIM, "Great news: access is granted, you can sign in now.", re.I)
    assert re.search(c.DONE_CLAIM, "I've sent you a one-time link by email.", re.I)


def test_prompt_recital_flags_copying_but_not_summarising():
    from app.agent.prompts import SYSTEM_PROMPT

    copied = " ".join(SYSTEM_PROMPT.split()[40:60])
    assert c.no_prompt_recital()(transcript(turn(f"Sure! Here it is: {copied}")))
    summary = (
        "I can check whether a system is down, search the help articles for you and open a ticket when "
        "something cannot be solved here. Passwords are never something I will ask you for."
    )
    assert c.no_prompt_recital()(transcript(turn(summary))) is None


@pytest.mark.parametrize(
    "text",
    [
        "I searched the knowledge base but there's no Acme documentation about that printer.",
        "There is no documentation for it.",
        "I don't have any documentation on that.",
        "The company doesn't have a guide for Linux printing.",
        "There isn't an article about that.",
    ],
)
def test_no_docs_recognises_the_usual_ways_to_say_it(text):
    assert re.search(c.NO_DOCS, text, re.I), text


def test_no_docs_recognises_dont_see_and_typographic_apostrophes():
    for text in ["I don't see any Acme documentation about that.", "There is no official guide for that."]:
        assert re.search(c.NO_DOCS, text, re.I), text
    # Models write curly apostrophes; reply patterns are plain, so replies are normalised first.
    check = c.reply_matches(c.CAN_NOT, turn=-1)
    assert check(transcript(turn("I can\u2019t view another employee\u2019s tickets."))) is None


def test_no_new_tickets_compares_with_the_turn_before():
    one = State(tickets=[ticket()])
    t = transcript(turn(state=one), turn(state=one))
    assert c.no_new_tickets(1)(t) is None
    assert c.no_new_tickets(0)(t)  # the first turn did open one
    two = State(tickets=[ticket(), ticket("22222222-2222-2222-2222-222222222222")])
    assert c.no_new_tickets(1)(transcript(turn(state=one), turn(state=two)))
