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
            ("Alice Nguyen", "alice.nguyen@acme.test", "IT Support Analyst"),
            ("Marco Silva", "marco.silva@acme.test", "Sales Representative"),
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
            ("Priya Patel", "priya.patel@globex.test", "Finance Analyst"),
            ("Tom Becker", "tom.becker@globex.test", "Support Agent"),
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
            ("Peter Gibbons", "peter.gibbons@initech.test", "Software Engineer"),
            ("Samir Nagheenanajar", "samir.n@initech.test", "Software Engineer"),
        ],
        "systems": [
            ("VPN", SystemStatus.operational),
            ("Email", SystemStatus.operational),
            ("TPS Reports Portal", SystemStatus.operational),
            ("Intranet", SystemStatus.degraded),
        ],
    },
]


async def seed() -> None:
    async with AdminSessionLocal() as session:
        for spec in DEMO_TENANTS:
            existing = await session.scalar(select(Tenant).where(Tenant.slug == spec["slug"]))
            if existing:
                print(f"skip: tenant '{spec['slug']}' already seeded")
                continue

            tenant = Tenant(name=spec["name"], slug=spec["slug"])
            session.add(tenant)
            await session.flush()  # populate tenant.id

            for full_name, email, job_title in spec["employees"]:
                session.add(
                    Employee(tenant_id=tenant.id, full_name=full_name, email=email, job_title=job_title)
                )
            for name, status in spec["systems"]:
                session.add(System(tenant_id=tenant.id, name=name, status=status))

            print(f"seeded: tenant '{spec['slug']}' ({tenant.id})")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
