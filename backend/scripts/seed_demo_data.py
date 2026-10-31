"""Seeds fictitious demo tenants. Idempotent: safe to run multiple times.

Uses the ADMIN session deliberately — seeding needs to write across tenants,
which the RLS-enforced app_runtime role cannot do.

Usage (from backend/):
    python -m scripts.seed_demo_data
"""

import asyncio

from sqlalchemy import select

from app.db.models import Employee, System, SystemStatus, Tenant
from app.db.session import AdminSessionLocal

DEMO_TENANTS = [
    {
        "name": "Acme Corp",
        "slug": "acme",
        "employees": [
            ("Alice Nguyen", "alice.nguyen@acme.test", "IT Support Analyst", True),
            ("Marco Silva", "marco.silva@acme.test", "Sales Representative", False),
        ],
        "systems": [
            ("VPN", SystemStatus.operational),
            ("Email", SystemStatus.operational),
            ("CRM", SystemStatus.degraded),
            ("Intranet", SystemStatus.operational),
        ],
    },
    {
        "name": "Globex Inc",
        "slug": "globex",
        "employees": [
            ("Priya Patel", "priya.patel@globex.test", "Finance Analyst", False),
            ("Tom Becker", "tom.becker@globex.test", "Support Agent", True),
        ],
        "systems": [
            ("VPN", SystemStatus.operational),
            ("Email", SystemStatus.outage),
            ("CRM", SystemStatus.operational),
            ("Payroll Portal", SystemStatus.operational),
        ],
    },
    {
        "name": "Initech",
        "slug": "initech",
        "employees": [
            ("Peter Gibbons", "peter.gibbons@initech.test", "Software Engineer", False),
            ("Samir Nagheenanajar", "samir.n@initech.test", "Software Engineer", False),
            ("Milton Waddams", "milton.waddams@initech.test", "IT Support", True),
        ],
        "systems": [
            ("VPN", SystemStatus.operational),
            ("Email", SystemStatus.operational),
            ("TPS Reports Portal", SystemStatus.operational),
            ("Intranet", SystemStatus.degraded),
        ],
    },
]


async def _sync_employees(session, tenant: Tenant, employees: list[tuple[str, str, str, bool]]) -> None:
    """Add employees an older seed did not have and refresh the support-agent flag, by email."""
    rows = await session.scalars(select(Employee).where(Employee.tenant_id == tenant.id))
    current = {e.email: e for e in rows}
    for full_name, email, job_title, is_support_agent in employees:
        known = current.get(email)
        if known is None:
            session.add(
                Employee(
                    tenant_id=tenant.id,
                    full_name=full_name,
                    email=email,
                    job_title=job_title,
                    is_support_agent=is_support_agent,
                )
            )
        else:
            known.is_support_agent = is_support_agent


async def seed() -> None:
    async with AdminSessionLocal() as session:
        for spec in DEMO_TENANTS:
            existing = await session.scalar(select(Tenant).where(Tenant.slug == spec["slug"]))
            if existing:
                await _sync_employees(session, existing, spec["employees"])
                print(f"ok:   tenant '{spec['slug']}' already seeded (employees synced)")
                continue

            tenant = Tenant(name=spec["name"], slug=spec["slug"])
            session.add(tenant)
            await session.flush()  # populate tenant.id

            for full_name, email, job_title, is_support_agent in spec["employees"]:
                session.add(
                    Employee(
                        tenant_id=tenant.id,
                        full_name=full_name,
                        email=email,
                        job_title=job_title,
                        is_support_agent=is_support_agent,
                    )
                )
            for name, status in spec["systems"]:
                session.add(System(tenant_id=tenant.id, name=name, status=status))

            print(f"seeded: tenant '{spec['slug']}' ({tenant.id})")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
