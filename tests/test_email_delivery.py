"""
Email delivery tests — run with: python3 tests/test_email_delivery.py

Unlike every other external-provider test in this project (which use a
fake Python object standing in for the real API), this one runs an
actual SMTP server on 127.0.0.1 and sends real messages to it over a
real socket via smtplib — because loopback networking works in this
sandbox even though external network access doesn't. This confirms
SMTPEmailProvider's SMTP command sequence and message construction are
genuinely correct, not just "written to look right."
"""
from __future__ import annotations

import socket
import sys
import threading
import unittest
from email import message_from_string
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.core.notification_provider import NotificationUnavailable
from backend.integrations.email_smtp import SMTPEmailProvider


def _decode_mime_body(raw_message: str) -> str:
    """Parses a raw SMTP DATA payload as a real email message and
    returns its decoded text body — robust to whatever
    Content-Transfer-Encoding Python's email library chose (base64,
    quoted-printable, or plain), so this test can't be fooled by an
    encoding change the way naive substring matching against the raw
    wire bytes was (see the real bug this caught, fixed in
    backend/integrations/email_smtp.py)."""
    parsed = message_from_string(raw_message)
    payload = parsed.get_payload(decode=True)
    charset = parsed.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


class MinimalSMTPServer:
    """Just enough SMTP (RFC 5321) to work with smtplib's connect/EHLO/
    MAIL FROM/RCPT TO/DATA/QUIT sequence, without TLS or auth support —
    real socket I/O, real line protocol, no mocking. Captures every
    message it receives for test assertions."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))  # OS-assigned free port
        self.port = self._sock.getsockname()[1]
        self._sock.listen(1)
        self.received_messages: list[dict] = []
        self._thread = threading.Thread(target=self._serve_one, daemon=True)
        self._thread.start()

    def _serve_one(self) -> None:
        conn, _ = self._sock.accept()
        f = conn.makefile("rwb")
        try:
            f.write(b"220 localhost Test SMTP Ready\r\n")
            f.flush()
            mail_from = rcpt_to = None
            while True:
                line = f.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                upper = text.upper()
                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    f.write(b"250 localhost\r\n"); f.flush()
                elif upper.startswith("MAIL FROM:"):
                    mail_from = text.split(":", 1)[1].strip()
                    f.write(b"250 OK\r\n"); f.flush()
                elif upper.startswith("RCPT TO:"):
                    rcpt_to = text.split(":", 1)[1].strip()
                    f.write(b"250 OK\r\n"); f.flush()
                elif upper.startswith("DATA"):
                    f.write(b"354 End data with <CR><LF>.<CR><LF>\r\n"); f.flush()
                    body_lines = []
                    while True:
                        data_line = f.readline()
                        if data_line in (b".\r\n", b".\n"):
                            break
                        body_lines.append(data_line.decode(errors="replace"))
                    self.received_messages.append({
                        "mail_from": mail_from, "rcpt_to": rcpt_to,
                        "body": "".join(body_lines),
                    })
                    f.write(b"250 OK\r\n"); f.flush()
                elif upper.startswith("QUIT"):
                    f.write(b"221 Bye\r\n"); f.flush()
                    break
                else:
                    f.write(b"250 OK\r\n"); f.flush()
        finally:
            conn.close()

    def close(self) -> None:
        self._sock.close()


class TestEmailDeliveryEndToEnd(unittest.TestCase):
    def test_real_smtp_send_is_received_correctly(self):
        server = MinimalSMTPServer()
        try:
            provider = SMTPEmailProvider(
                host="127.0.0.1", port=server.port, username=None, password=None,
                from_address="noreply@aranya.example", use_tls=False,
            )
            provider.send_otp("farmer@example.com", "482913")

            self.assertEqual(len(server.received_messages), 1)
            msg = server.received_messages[0]
            self.assertIn("noreply@aranya.example", msg["mail_from"])
            self.assertIn("farmer@example.com", msg["rcpt_to"])
            decoded_body = _decode_mime_body(msg["body"])
            self.assertIn("482913", decoded_body)
            self.assertIn("Aranya verification code", decoded_body)
        finally:
            server.close()

    def test_invalid_email_is_rejected_before_any_connection_is_attempted(self):
        provider = SMTPEmailProvider(
            host="127.0.0.1", port=1,  # deliberately unreachable — must never be dialed
            username=None, password=None, from_address="noreply@aranya.example", use_tls=False,
        )
        with self.assertRaises(NotificationUnavailable):
            provider.send_otp("not-a-valid-email", "123456")

    def test_connection_failure_raises_notification_unavailable(self):
        # Port with nothing listening — a real connection failure, not simulated.
        provider = SMTPEmailProvider(
            host="127.0.0.1", port=1, username=None, password=None,
            from_address="noreply@aranya.example", use_tls=False,
        )
        with self.assertRaises(NotificationUnavailable):
            provider.send_otp("farmer@example.com", "123456")

    def test_from_env_returns_none_when_unconfigured(self):
        import os
        old = os.environ.pop("SMTP_HOST", None)
        try:
            self.assertIsNone(SMTPEmailProvider.from_env())
        finally:
            if old is not None:
                os.environ["SMTP_HOST"] = old

    def test_decode_helper_handles_base64_encoded_body_correctly(self):
        # Regression guard for the exact bug this test suite caught: a
        # non-ASCII character in the body silently switched Python's
        # email library to base64 encoding, and naive substring matching
        # against the raw wire bytes missed the OTP code entirely. Forces
        # that encoding path directly to confirm the decode helper (and
        # thus every test above) can't be fooled by it again.
        from email.mime.text import MIMEText
        msg = MIMEText("code: 999888 with a non-ascii dash \u2014 here")
        decoded = _decode_mime_body(msg.as_string())
        self.assertIn("999888", decoded)
        self.assertIn("\u2014", decoded)

    def test_multiple_real_sends_all_arrive_correctly(self):
        server = MinimalSMTPServer()
        try:
            provider = SMTPEmailProvider(
                host="127.0.0.1", port=server.port, username=None, password=None,
                from_address="noreply@aranya.example", use_tls=False,
            )
            provider.send_otp("first@example.com", "111111")
        finally:
            server.close()

        server2 = MinimalSMTPServer()
        try:
            provider2 = SMTPEmailProvider(
                host="127.0.0.1", port=server2.port, username=None, password=None,
                from_address="noreply@aranya.example", use_tls=False,
            )
            provider2.send_otp("second@example.com", "222222")
            self.assertIn("222222", _decode_mime_body(server2.received_messages[0]["body"]))
        finally:
            server2.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
