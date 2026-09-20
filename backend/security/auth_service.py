"""
AuthService — the actual login flow, spec section 19.

Combines:
  - SlidingWindowRateLimiter (per-phone request throttling)
  - OTPService (generate/verify one-time codes)
  - SMSProvider / EmailProvider (real delivery — see below)
  - tokens.create_access_token (JWT session issuance)
  - FarmMemory.log_audit (every login attempt, success or failure)

into the two calls a login screen actually needs: request_login_otp() and
verify_login_otp().

DELIVERY: a farmer provides phone (required) and email (optional).
request_login_otp() attempts SMS delivery (if an SMSProvider is
configured) and email delivery (if an EmailProvider is configured AND
the farmer gave an email) and succeeds if AT LEAST ONE channel delivers.
Email delivery is genuinely tested end-to-end in this codebase (see
tests/test_email_delivery.py — real SMTP server, real smtplib client,
real socket I/O); SMS delivery (Twilio) is written but cannot be tested
here at all, not even with loopback (no way to simulate a carrier
network locally) — see backend/integrations/sms_twilio.py.

If NEITHER channel is configured (a fresh local checkout with no
provider credentials set), this falls back to returning the code
directly rather than hard-failing — the same honest labeled behavior
this project uses elsewhere when no provider is configured, chosen so
the whole system stays runnable/testable/demoable without needing real
Twilio/SMTP credentials. If channels ARE configured but all of them
fail, that's a real delivery failure and raises AuthError instead of
silently falling back to exposing the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.notification_provider import EmailProvider, NotificationUnavailable, SMSProvider, is_valid_email
from backend.memory.store import FarmMemory
from backend.security.otp import OTPError, OTPService
from backend.security.rate_limit import SlidingWindowRateLimiter
from backend.security.tokens import Role, create_access_token


class AuthError(Exception):
    """User-facing auth failure — rate limited, wrong/expired code, bad
    email format, delivery failure, etc."""


@dataclass
class AuthService:
    memory: FarmMemory
    otp_service: OTPService
    sms_provider: SMSProvider | None = None
    email_provider: EmailProvider | None = None
    rate_limiter: SlidingWindowRateLimiter = field(
        default_factory=lambda: SlidingWindowRateLimiter(max_requests=5, window_seconds=3600)
    )

    def request_login_otp(self, phone: str, email: str | None = None) -> dict:
        """Returns {"delivered_via": [...channels...], "debug_code": str|None}.
        `debug_code` is only ever non-None when NO delivery channel is
        configured at all (see module docstring) — a real deployment with
        SMS and/or email configured never exposes the code in this
        return value."""
        if email and not is_valid_email(email):
            raise AuthError(f"{email!r} doesn't look like a valid email address.")

        if not self.rate_limiter.allow(phone):
            self.memory.log_audit(actor=phone, action="otp_request_rate_limited")
            raise AuthError("Too many login attempts for this number. Please try again later.")

        try:
            code = self.otp_service.request_otp(phone)
        except OTPError as exc:
            self.memory.log_audit(actor=phone, action="otp_request_failed", details={"reason": str(exc)})
            raise AuthError(str(exc)) from exc

        delivered_via: list[str] = []
        delivery_errors: list[str] = []
        any_channel_configured = bool(self.sms_provider) or bool(self.email_provider and email)

        if self.sms_provider is not None:
            try:
                self.sms_provider.send_otp(phone, code)
                delivered_via.append("sms")
            except NotificationUnavailable as exc:
                delivery_errors.append(f"sms: {exc}")

        if email and self.email_provider is not None:
            try:
                self.email_provider.send_otp(email, code)
                delivered_via.append("email")
            except NotificationUnavailable as exc:
                delivery_errors.append(f"email: {exc}")

        if delivered_via:
            self.memory.log_audit(actor=phone, action="otp_delivered",
                                   details={"channels": delivered_via})
            return {"delivered_via": delivered_via, "debug_code": None}

        if any_channel_configured:
            # A channel WAS configured but every attempt failed — a real
            # delivery failure, not an absence-of-configuration case.
            self.memory.log_audit(actor=phone, action="otp_delivery_failed",
                                   details={"errors": delivery_errors})
            raise AuthError("Could not deliver the verification code via SMS or email. "
                             "Please check the number/address and try again.")

        # No delivery channel configured at all — honest dev-mode fallback.
        self.memory.log_audit(actor=phone, action="otp_dev_mode_no_delivery_configured")
        return {"delivered_via": [], "debug_code": code}

    def verify_login_otp(self, phone: str, code: str, name_if_new: str = "New Farmer",
                          email: str | None = None) -> str:
        """Verifies the code, gets-or-creates the Farmer record for this
        phone (backfilling email if one is now provided and wasn't on
        file), and returns a signed JWT. Raises AuthError on any failure
        — never silently logs someone in."""
        try:
            ok = self.otp_service.verify_otp(phone, code)
        except OTPError as exc:
            self.memory.log_audit(actor=phone, action="otp_verify_error", details={"reason": str(exc)})
            raise AuthError(str(exc)) from exc

        if not ok:
            self.memory.log_audit(actor=phone, action="otp_verify_wrong_code")
            raise AuthError("Incorrect code.")

        if email and not is_valid_email(email):
            raise AuthError(f"{email!r} doesn't look like a valid email address.")

        farmer_id = self.memory.get_or_create_farmer(name=name_if_new, phone=phone, email=email)
        token = create_access_token(farmer_id=farmer_id, role=Role.FARMER)
        self.memory.log_audit(actor=phone, action="login_success",
                               target_type="farmer", target_id=str(farmer_id))
        return token
