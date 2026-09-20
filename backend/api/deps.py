"""
FastAPI auth dependencies.

STATUS: written but not executed here (no fastapi installed in the
authoring sandbox). The logic it calls into (backend.security.tokens) IS
executed and unit-tested — see tests/test_auth.py. This file is the thin
FastAPI wiring on top of that tested logic.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.memory.store import FarmMemory
from backend.security.tokens import AuthError, Role, SessionClaims, decode_access_token

_bearer_scheme = HTTPBearer()


def get_current_claims(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> SessionClaims:
    try:
        return decode_access_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_farm_access(farm_id: int, claims: SessionClaims, memory: FarmMemory) -> None:
    """Spec section 19: authorization, not just authentication. A farmer
    may only act on their own farm; experts/admins may act on any farm
    (they need to for consultations). Raises 403, never silently allows."""
    if claims.role in (Role.EXPERT, Role.ADMIN):
        return
    if not memory.farmer_owns_farm(claims.farmer_id, farm_id):
        raise HTTPException(status_code=403, detail="You do not have access to this farm.")
