"""
Twilio SMS provider — a real implementation of SMSProvider.

STATUS: written, NOT executed in the authoring sandbox. Unlike
SMTPEmailProvider, this one genuinely cannot be tested here even with
loopback networking working — email delivery only needed a server that
speaks SMTP, which is simple enough to implement from scratch, but SMS
delivery needs an actual telecom carrier network, a real Twilio account,
and a real phone number to receive it, none of which can be simulated
locally. The request/response shape below matches Twilio's standard
Messages REST API; verify against real credentials on a machine with
network access and a real phone to receive the test message.
"""

from __future__ import annotations

import os

import requests

from backend.core.notification_provider import NotificationUnavailable

BASE_URL = "https://api.twilio.com/2010-04-01/Accounts"
REQUEST_TIMEOUT_SECONDS = 15


def _otp_sms_body(code: str) -> str:
    return f"Your Aranya verification code is {code}. It expires in 5 minutes."


class TwilioSMSProvider:
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    @classmethod
    def from_env(cls) -> "TwilioSMSProvider | None":
        sid = os.environ.get("TWILIO_ACCOUNT_SID")
        token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        if not (sid and token and from_number):
            return None
        return cls(account_sid=sid, auth_token=token, from_number=from_number)

    def send_otp(self, phone: str, code: str) -> None:
        try:
            resp = requests.post(
                f"{BASE_URL}/{self._account_sid}/Messages.json",
                auth=(self._account_sid, self._auth_token),
                data={"To": phone, "From": self._from_number, "Body": _otp_sms_body(code)},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise NotificationUnavailable(f"SMS delivery failed: {exc}") from exc
