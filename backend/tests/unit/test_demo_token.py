import base64
import json
import uuid

import pytest

from app.services import demo_token
from app.services.demo_token import InvalidToken, issue, verify

SECRET = "s" * 40
TENANT = uuid.uuid4()
PERSON = uuid.uuid4()


def mint(**kwargs):
    return issue(SECRET, tenant_id=TENANT, employee_id=PERSON, ttl_seconds=3600, **kwargs)


def test_a_token_round_trips_with_its_claims():
    token, issued = mint(now=1_000)
    claims = verify(SECRET, token, now=1_500)
    assert (claims.tenant_id, claims.employee_id) == (TENANT, PERSON)
    assert claims.session_id == issued.session_id
    assert claims.expires_at == 1_000 + 3600


def test_every_token_gets_its_own_session_id():
    assert mint()[1].session_id != mint()[1].session_id


def test_an_expired_token_is_refused():
    token, _ = mint(now=1_000)
    with pytest.raises(InvalidToken, match="expired"):
        verify(SECRET, token, now=1_000 + 3600)


def test_a_token_signed_with_another_secret_is_refused():
    token, _ = mint()
    with pytest.raises(InvalidToken, match="signature"):
        verify("t" * 40, token)


def test_changing_the_payload_breaks_the_signature():
    token, _ = mint()
    payload, signature = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=="))
    data["e"] = str(uuid.uuid4())  # pretend to be someone else
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidToken, match="signature"):
        verify(SECRET, f"{forged}.{signature}")


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "....", "e30.e30", "not base64.at all"])
def test_garbage_is_refused_without_raising_anything_else(junk):
    with pytest.raises(InvalidToken):
        verify(SECRET, junk)


def test_a_correctly_signed_but_unknown_version_is_refused():
    payload = json.dumps({"v": 99, "t": str(TENANT), "e": str(PERSON), "s": "x", "x": 9_999_999_999}).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(demo_token._sign(SECRET, payload)).rstrip(b"=").decode()
    with pytest.raises(InvalidToken, match="version"):
        verify(SECRET, f"{body}.{signature}")
