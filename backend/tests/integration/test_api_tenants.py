import httpx
import pytest

from app.main import app

pytestmark = pytest.mark.integration


async def test_lists_tenants(two_tenants):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tenants")

    assert response.status_code == 200
    ids = {t["id"] for t in response.json()}
    assert {str(two_tenants.a.id), str(two_tenants.b.id)} <= ids
