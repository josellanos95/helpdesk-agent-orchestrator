"""Signed demo sessions.

A token is `base64url(payload).base64url(hmac_sha256(secret, payload))`. The payload carries the tenant, the
employee, a random session id (budgets and rate limits are counted per session) and an expiry. It is a
small, dependency-free cousin of a JWT: one algorithm, no negotiation, so there is no "alg: none" to forget.

What this does and does not prove: anyone can mint a token for any fictitious person (that is the demo), so
a token proves "this browser session chose to be this person", not who they really are. What it buys is that
the choice is made once and then enforced by the server: tenant, employee and role stop being per-request
claims the caller can change.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

VERSION = 1


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Claims:
    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    session_id: str
    expires_at: int  # unix seconds


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, payload: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()


def issue(
    secret: str,
    *,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    ttl_seconds: int,
    now: float | None = None,
) -> tuple[str, Claims]:
    claims = Claims(
        tenant_id=tenant_id,
        employee_id=employee_id,
        session_id=uuid.uuid4().hex,
        expires_at=int((time.time() if now is None else now) + ttl_seconds),
    )
    payload = json.dumps(
        {
            "v": VERSION,
            "t": str(claims.tenant_id),
            "e": str(claims.employee_id),
            "s": claims.session_id,
            "x": claims.expires_at,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_b64(payload)}.{_b64(_sign(secret, payload))}", claims


def verify(secret: str, token: str, *, now: float | None = None) -> Claims:
    try:
        payload_part, signature_part = token.split(".")
        payload = _unb64(payload_part)
        signature = _unb64(signature_part)
    except (ValueError, TypeError) as exc:
        raise InvalidToken("malformed token") from exc

    if not hmac.compare_digest(signature, _sign(secret, payload)):
        raise InvalidToken("bad signature")
    try:
        data = json.loads(payload)
        if data["v"] != VERSION:
            raise InvalidToken("unknown token version")
        claims = Claims(
            tenant_id=uuid.UUID(data["t"]),
            employee_id=uuid.UUID(data["e"]),
            session_id=str(data["s"]),
            expires_at=int(data["x"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidToken("malformed payload") from exc
    if claims.expires_at <= (time.time() if now is None else now):
        raise InvalidToken("expired")
    return claims
