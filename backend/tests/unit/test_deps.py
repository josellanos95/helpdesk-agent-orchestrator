import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.api.deps import TENANT_HEADER, get_tenant_id


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> dict[str, str]:
        return {"tenant_id": str(tenant_id)}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_valid_header_is_parsed(client):
    tenant_id = uuid.uuid4()
    response = await client.get("/whoami", headers={TENANT_HEADER: str(tenant_id)})
    assert response.status_code == 200
    assert response.json() == {"tenant_id": str(tenant_id)}


@pytest.mark.parametrize("value", ["", "not-a-uuid", "1234", "' OR 1=1 --"])
async def test_malformed_header_is_a_400(client, value):
    response = await client.get("/whoami", headers={TENANT_HEADER: value})
    assert response.status_code == 400


async def test_missing_header_is_rejected(client):
    response = await client.get("/whoami")
    assert response.status_code == 422
