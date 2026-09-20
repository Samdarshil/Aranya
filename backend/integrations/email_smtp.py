"""
SMTP email provider — a real implementation of EmailProvider.

STATUS: different from every other external integration in this
codebase. Gemini/OpenWeatherMap/Agmarknet/Google Speech all need real
egress network access this sandbox doesn't have, so those are
written-but-never-executed. This one is genuinely tested end-to-end —
loopback networking (127.0.0.1) works here even though external network
access doesn't, so tests/test_email_delivery.py runs a real minimal SMTP
server on localhost and sends real messages to it through this exact
class via smtplib, then inspects what was actually received. That
confirms the message construction, SMTP command sequence, and TLS/auth
code paths are correct — it does NOT confirm behavior against a real
mail provider's specific quirks (Gmail, SES, SendGrid's SMTP relay, etc
each have their own auth/rate-limit peculiarities), so still verify
against your actual provider before relying on this in production.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

from backend.core.notification_provider import NotificationUnavailable, is_valid_email

DEFAULT_SUBJECT = "Your Aranya verification code"
CONNECT_TIMEOUT_SECONDS = 10


def _otp_email_body(code: str) -> str:
    return (
        f"Your Aranya verification code is: {code}\n\n"
        f"This code expires in 5 minutes. If you didn't request this, "
        f"you can safely ignore this email.\n\n"
        f"- Aranya AI"
    )


class SMTPEmailProvider:
    name = "smtp"

    def __init__(self, host: str, port: int, username: str | None, password: str | None,
                 from_address: str, use_tls: bool = True):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._use_tls = use_tls

    @classmethod
    def from_env(cls) -> "SMTPEmailProvider | None":
        host = os.environ.get("SMTP_HOST")
        if not host:
            return None
        return cls(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USERNAME"),
            password=os.environ.get("SMTP_PASSWORD"),
            from_address=os.environ.get("SMTP_FROM_EMAIL", "noreply@aranya.example"),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        )

    def send_otp(self, email: str, code: str) -> None:
        if not is_valid_email(email):
            raise NotificationUnavailable(f"{email!r} is not a valid email address.")

        message = MIMEText(_otp_email_body(code))
        message["Subject"] = DEFAULT_SUBJECT
        message["From"] = self._from_address
        message["To"] = email

        try:
            with smtplib.SMTP(self._host, self._port, timeout=CONNECT_TIMEOUT_SECONDS) as server:
                if self._use_tls:
                    server.starttls()
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.sendmail(self._from_address, [email], message.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationUnavailable(f"Email delivery failed: {exc}") from exc
