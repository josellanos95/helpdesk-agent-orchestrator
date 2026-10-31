from decimal import Decimal

import pytest

from app.agent.tools import default_registry
from app.llm.base import Usage
from app.llm.pricing import cost_usd, is_priced

IDENTITY_FIELDS = {"tenant_id", "employee_id", "conversation_id", "tenant", "employee"}


def test_no_tool_lets_the_model_choose_who_it_acts_for():
    """Tenant, employee and conversation come from the authenticated request. If a tool ever
    grows such an argument, a prompt injection could aim it at someone else."""
    for schema in default_registry().schemas():
        properties = set(schema["function"]["parameters"].get("properties", {}))
        assert not (properties & IDENTITY_FIELDS), schema["function"]["name"]


def test_every_tool_schema_is_well_formed():
    for schema in default_registry().schemas():
        fn = schema["function"]
        assert schema["type"] == "function"
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_cost_uses_input_and_output_prices():
    # gpt-5-mini: $0.25 in / $2.00 out per million tokens
    assert cost_usd("gpt-5-mini", Usage(prompt_tokens=1000, completion_tokens=500)) == Decimal("0.00125")


def test_cost_matches_dated_model_snapshots():
    assert is_priced("gpt-5-mini-2025-08-07")
    assert cost_usd("gpt-5-mini-2025-08-07", Usage(1_000_000, 0)) == Decimal("0.25")


def test_gpt_5_nano_is_not_mistaken_for_gpt_5_mini():
    assert cost_usd("gpt-5-nano", Usage(1_000_000, 0)) == Decimal("0.05")


@pytest.mark.parametrize("model", ["some-unknown-model", "gpt-5", ""])
def test_unknown_models_cost_nothing_and_are_flagged(model):
    assert not is_priced(model)
    assert cost_usd(model, Usage(1000, 1000)) == Decimal(0)


def test_exactly_the_sensitive_tools_require_approval():
    """Adding a tool forces a decision here: does it change something a human should sign off on?"""
    registry = default_registry()
    needs_approval = {
        name
        for name in (
            "check_system_status",
            "create_ticket",
            "list_my_tickets",
            "escalate_to_human",
            "list_my_requests",
            "reset_password",
            "grant_system_access",
        )
        if registry.get(name).requires_approval
    }
    assert needs_approval == {"reset_password", "grant_system_access"}


def test_every_registered_tool_is_accounted_for_above():
    names = {s["function"]["name"] for s in default_registry().schemas()}
    assert names == {
        "check_system_status",
        "create_ticket",
        "list_my_tickets",
        "escalate_to_human",
        "list_my_requests",
        "reset_password",
        "grant_system_access",
    }
