import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import tenant_scoped_session

TENANT_HEADER = "X-Tenant-Id"


async def get_tenant_id(x_tenant_id: str = Header(..., alias=TENANT_HEADER)) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {TENANT_HEADER} header") from exc


async def get_db(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> AsyncGenerator[AsyncSession]:
    async for session in tenant_scoped_session(tenant_id):
        yield session
