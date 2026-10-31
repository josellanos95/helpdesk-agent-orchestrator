"""Talk to the real agent from a terminal. Costs a few cents of OpenAI credit.

Needs OPENAI_API_KEY in backend/.env and a seeded database (scripts.seed_demo_data, scripts.seed_kb).
It goes through the same `run_agent` as the API, with the same tools and knowledge base.

Usage (from backend/):
    python -m scripts.chat_cli --tenant acme --employee marco
    python -m scripts.chat_cli --tenant globex --employee priya --trace
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from app.agent.runner import run_agent
from app.agent.tools import default_registry
from app.config import get_settings
from app.db.models import AgentStep, Conversation, Employee, Tenant
from app.db.session import AdminSessionLocal, tenant_session
from app.llm.embeddings import build_embedder
from app.llm.openai_client import OpenAIClient


async def main(tenant_slug: str, employee_hint: str, show_trace: bool) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set (put it in backend/.env).")
    llm = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
    embedder = build_embedder(settings)

    async with AdminSessionLocal() as admin:
        tenant = await admin.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            raise SystemExit(f"No tenant '{tenant_slug}'. Run: python -m scripts.seed_demo_data")

    async with tenant_session(tenant.id) as session:
        employees = list(await session.scalars(select(Employee).order_by(Employee.full_name)))
        employee = next((e for e in employees if employee_hint.lower() in e.full_name.lower()), None)
        if employee is None:
            raise SystemExit(f"No employee matching '{employee_hint}': {[e.full_name for e in employees]}")
        conversation = Conversation(tenant_id=tenant.id, employee_id=employee.id)
        session.add(conversation)
        await session.flush()
        conversation_id, employee_id = conversation.id, employee.id

    registry = default_registry()
    print(f"[{tenant.name}] you are {employee.full_name}; model={llm.model}. Empty line to quit.")
    while text := input("you> ").strip():
        result = await run_agent(
            scope=lambda: tenant_session(tenant.id),
            llm=llm,
            registry=registry,
            tenant_id=tenant.id,
            conversation_id=conversation_id,
            employee_id=employee_id,
            user_text=text,
            max_steps=settings.agent_max_steps,
            embedder=embedder,
        )
        if show_trace:
            async with tenant_session(tenant.id) as session:
                steps = await session.scalars(
                    select(AgentStep).where(AgentStep.run_id == result.run_id).order_by(AgentStep.step_index)
                )
                for step in steps:
                    print(f"   · {step.kind}:{step.name} {step.latency_ms}ms", json.dumps(step.output)[:160])
        print(f"agent> {result.reply}")
        tokens = f"{result.prompt_tokens}+{result.completion_tokens} tokens"
        print(f"   [{result.status.value}] {tokens}, ${result.cost_usd}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--employee", default="marco")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.tenant, args.employee, args.trace))
