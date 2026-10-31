"""Talk to the real agent from a terminal. Costs a few cents of OpenAI credit.

Needs OPENAI_API_KEY in backend/.env and a seeded database.

Usage (from backend/):
    python -m scripts.chat_cli --tenant acme --employee alice
"""

import argparse
import asyncio
import json

from sqlalchemy import select

from app.agent.runner import run_agent
from app.agent.tools import default_registry
from app.config import get_settings
from app.db.models import Conversation, Employee, Tenant
from app.db.session import AdminSessionLocal, tenant_scoped_session
from app.llm.openai_client import OpenAIClient


async def main(tenant_slug: str, employee_hint: str, show_trace: bool) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set (put it in backend/.env).")
    llm = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)

    async with AdminSessionLocal() as admin:
        tenant = await admin.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            raise SystemExit(f"No tenant '{tenant_slug}'. Run: python -m scripts.seed_demo_data")

    conversation_id = None
    print(f"[{tenant.name}] model={llm.model}. Empty line to quit.")
    while (text := input("you> ").strip()):
        async for session in tenant_scoped_session(tenant.id):
            employees = list(await session.scalars(select(Employee).order_by(Employee.full_name)))
            employee = next((e for e in employees if employee_hint.lower() in e.full_name.lower()), None)
            if employee is None:
                names = [e.full_name for e in employees]
                raise SystemExit(f"No employee matching '{employee_hint}': {names}")
            if conversation_id is None:
                conversation = Conversation(tenant_id=tenant.id, employee_id=employee.id)
                session.add(conversation)
                await session.flush()
                conversation_id = conversation.id
            result = await run_agent(
                session=session,
                llm=llm,
                registry=default_registry(),
                tenant_id=tenant.id,
                conversation_id=conversation_id,
                employee=employee,
                user_text=text,
                max_steps=settings.agent_max_steps,
            )
            if show_trace:
                from app.db.models import AgentStep

                for step in await session.scalars(
                    select(AgentStep).where(AgentStep.run_id == result.run_id).order_by(AgentStep.step_index)
                ):
                    print(f"   · {step.kind}:{step.name} {step.latency_ms}ms", json.dumps(step.output)[:160])
        print(f"agent> {result.reply}")
        tokens = f"{result.prompt_tokens}+{result.completion_tokens} tokens"
        print(f"   [{result.status.value}] {tokens}, ${result.cost_usd}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--employee", default="alice")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.tenant, args.employee, args.trace))
