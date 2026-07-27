import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import Tenant
from app.db.session import AdminSessionLocal

router = APIRouter()


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str

    model_config = {"from_attributes": True}


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants() -> list[Tenant]:
    async with AdminSessionLocal() as session:
        result = await session.scalars(select(Tenant).order_by(Tenant.name))
        return list(result)
