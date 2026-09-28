"""
JWT session tokens — spec section 19.

Real, tested (PyJWT is available in the authoring sandbox — unlike
fastapi/sqlalchemy, no network install was needed). Issued only after
OTPService.verify_otp() succeeds — see backend/api/routes_auth.py.

JWT_SECRET_KEY must be set via environment variable in any real
deployment; the fallback here exists only so tests can run without a
.env file, and is deliberately obviously-not-production (loud value,
plus is_using_dev_secret() so calling code can refuse to serve real
traffic on it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt

_DEV_SECRET = "INSECURE-DEV-ONLY-SECRET-DO-NOT-USE-IN-PRODUCTION"
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_HOURS = 12


class Role(str, Enum):
    FARMER = "farmer"
    EXPERT = "expert"
    ADMIN = "admin"


class AuthError(Exception):
    """Raised for any token problem — expired, malformed, or invalid
    signature. Message is safe to show the user."""


def _secret() -> str:
    return os.environ.get("JWT_SECRET_KEY", _DEV_SECRET)


def is_using_dev_secret() -> bool:
    """Deployment code should check this at startup and refuse to serve
    real traffic if True — see docs/STATUS.md."""
    return "JWT_SECRET_KEY" not in os.environ


@dataclass(frozen=True)
class SessionClaims:
    farmer_id: int
    role: Role
    issued_at: datetime
    expires_at: datetime


def create_access_token(farmer_id: int, role: Role = Role.FARMER) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(farmer_id),
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> SessionClaims:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired. Please log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid session token.") from exc

    return SessionClaims(
        farmer_id=int(payload["sub"]),
        role=Role(payload["role"]),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )


def require_role(claims: SessionClaims, *allowed: Role) -> None:
    """Spec section 19: role-based permissions. Raises AuthError if the
    caller's role isn't in `allowed` — e.g. require_role(claims,
    Role.EXPERT, Role.ADMIN) for an endpoint only experts/admins may use."""
    if claims.role not in allowed:
        raise AuthError(f"Role '{claims.role.value}' is not permitted to perform this action.")
