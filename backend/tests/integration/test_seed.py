import pytest
from sqlalchemy import delete, select

from app.db.models import Employee, Tenant
from app.db.session import AdminSessionLocal
from scripts.seed_demo_data import DEMO_TENANTS, seed

pytestmark = pytest.mark.integration

DEMO_SLUGS = [t["slug"] for t in DEMO_TENANTS]


@pytest.fixture
async def clean_demo_tenants():
    async def wipe():
        async with AdminSessionLocal() as session:
            await session.execute(delete(Tenant).where(Tenant.slug.in_(DEMO_SLUGS)))
            await session.commit()

    await wipe()
    yield
    await wipe()


async def employees_by_email() -> dict[str, Employee]:
    async with AdminSessionLocal() as session:
        rows = await session.scalars(select(Employee).join(Tenant).where(Tenant.slug.in_(DEMO_SLUGS)))
        return {e.email: e for e in rows}


async def test_seeding_is_idempotent_and_every_demo_tenant_has_a_support_agent(clean_demo_tenants):
    await seed()
    first = await employees_by_email()
    await seed()
    second = await employees_by_email()

    assert len(first) == len(second) == sum(len(t["employees"]) for t in DEMO_TENANTS)
    for spec in DEMO_TENANTS:
        agents = [
            e for e in second.values() if e.is_support_agent and e.email.endswith(f"@{spec['slug']}.test")
        ]
        assert agents, f"{spec['slug']} has nobody who can approve requests"


async def test_reseeding_repairs_an_older_database(clean_demo_tenants):
    """An existing demo database (seeded before support agents existed) gets the flag and new people."""
    await seed()
    async with AdminSessionLocal() as session:
        alice = await session.scalar(select(Employee).where(Employee.email == "alice.nguyen@acme.test"))
        alice.is_support_agent = False
        await session.execute(delete(Employee).where(Employee.email == "milton.waddams@initech.test"))
        await session.commit()

    await seed()
    people = await employees_by_email()
    assert people["alice.nguyen@acme.test"].is_support_agent is True
    assert "milton.waddams@initech.test" in people
