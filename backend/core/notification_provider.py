"""
OTP delivery provider abstraction — spec section 19/20.

Same Protocol + honest-unavailability pattern as every other provider in
this codebase. Two channels: SMS and Email, either or both may be
configured. AuthService (backend/security/auth_service.py) attempts
whichever channels are configured and succeeds if at least one delivers.
"""

from __future__ import annotations

import re
from typing import Protocol

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NotificationUnavailable(Exception):
    """Raised when an OTP could not be delivered via this channel — no
    provider configured, network/API failure, or an invalid recipient.
    Callers must treat this as 'this channel failed', not silently
    pretend delivery happened."""


def is_valid_email(email: str) -> bool:
    """Minimal real format validation — not a full RFC 5322 validator
    (those are notoriously over-engineered for marginal benefit), just
    enough to reject obviously-malformed input before attempting delivery
    or storage."""
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


class SMSProvider(Protocol):
    name: str

    def send_otp(self, phone: str, code: str) -> None:
        """Raises NotificationUnavailable on any failure."""
        ...


class EmailProvider(Protocol):
    name: str

    def send_otp(self, email: str, code: str) -> None:
        """Raises NotificationUnavailable on any failure."""
        ...
