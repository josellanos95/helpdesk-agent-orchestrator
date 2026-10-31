import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import AuditLog

pytestmark = pytest.mark.integration


async def test_the_app_can_write_and_read_audit_entries(two_tenants, as_tenant):
    async with as_tenant(two_tenants.a.id) as session:
        session.add(AuditLog(tenant_id=two_tenants.a.id, actor_type="human", action="test", subject="x"))
    async with as_tenant(two_tenants.a.id) as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
    assert "test" in actions


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'tampered'", "DELETE FROM audit_log"],
)
async def test_the_app_cannot_edit_or_erase_the_audit_log(two_tenants, as_tenant, statement):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with as_tenant(two_tenants.a.id) as session:
            await session.execute(text(statement))
