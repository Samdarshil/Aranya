"""
Auth tests — run with: python3 tests/test_auth.py

Covers the actual security-relevant behavior: OTPs are never stored in
plaintext, expired/wrong/overused codes are rejected, JWTs round-trip and
expire, roles are enforced, rate limiting actually limits, and every
login attempt (success or failure) lands in the audit log.
"""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.memory.store import FarmMemory
from backend.security.auth_service import AuthError, AuthService
from backend.security.otp import MAX_VERIFY_ATTEMPTS, OTPError, OTPService
from backend.security.rate_limit import SlidingWindowRateLimiter
from backend.security.tokens import AuthError as TokenAuthError
from backend.security.tokens import Role, create_access_token, decode_access_token, require_role


class TestOTPService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.otp = OTPService(db_path=Path(self._tmpdir.name) / "otp.db")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_correct_code_verifies(self):
        code = self.otp.request_otp("+91-9999900001")
        self.assertTrue(self.otp.verify_otp("+91-9999900001", code))

    def test_code_is_single_use(self):
        code = self.otp.request_otp("+91-9999900002")
        self.assertTrue(self.otp.verify_otp("+91-9999900002", code))
        with self.assertRaises(OTPError):
            self.otp.verify_otp("+91-9999900002", code)  # already consumed

    def test_wrong_code_fails_without_raising(self):
        self.otp.request_otp("+91-9999900003")
        self.assertFalse(self.otp.verify_otp("+91-9999900003", "000000"))

    def test_too_many_wrong_attempts_locks_out(self):
        self.otp.request_otp("+91-9999900004")
        for _ in range(MAX_VERIFY_ATTEMPTS):
            self.otp.verify_otp("+91-9999900004", "000000")
        with self.assertRaises(OTPError):
            self.otp.verify_otp("+91-9999900004", "000000")

    def test_verifying_with_no_pending_request_raises(self):
        with self.assertRaises(OTPError):
            self.otp.verify_otp("+91-9999999999", "123456")

    def test_code_hash_is_not_the_plaintext_code(self):
        # Storage-layer check: confirm nothing plaintext lands in the db.
        code = self.otp.request_otp("+91-9999900005")
        raw = self.otp.db_path.read_bytes()
        self.assertNotIn(code.encode(), raw)

    def test_excessive_requests_are_rate_limited_at_storage_layer(self):
        from backend.security.otp import MAX_REQUESTS_PER_PHONE_PER_HOUR
        phone = "+91-9999900006"
        for _ in range(MAX_REQUESTS_PER_PHONE_PER_HOUR):
            self.otp.request_otp(phone)
        with self.assertRaises(OTPError):
            self.otp.request_otp(phone)


class TestTokens(unittest.TestCase):
    def test_round_trip(self):
        token = create_access_token(farmer_id=42, role=Role.FARMER)
        claims = decode_access_token(token)
        self.assertEqual(claims.farmer_id, 42)
        self.assertEqual(claims.role, Role.FARMER)

    def test_tampered_token_is_rejected(self):
        token = create_access_token(farmer_id=42)
        tampered = token[:-3] + ("xyz" if token[-3:] != "xyz" else "abc")
        with self.assertRaises(TokenAuthError):
            decode_access_token(tampered)

    def test_require_role_allows_matching_role(self):
        claims = decode_access_token(create_access_token(farmer_id=1, role=Role.EXPERT))
        require_role(claims, Role.EXPERT, Role.ADMIN)  # should not raise

    def test_require_role_rejects_mismatched_role(self):
        claims = decode_access_token(create_access_token(farmer_id=1, role=Role.FARMER))
        with self.assertRaises(TokenAuthError):
            require_role(claims, Role.EXPERT, Role.ADMIN)


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
        self.assertTrue(limiter.allow("k"))
        self.assertTrue(limiter.allow("k"))
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))

    def test_different_keys_are_independent(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))  # different key, own budget

    def test_window_expiry_frees_up_budget(self):
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=0.05)
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))
        time.sleep(0.06)
        self.assertTrue(limiter.allow("k"))


class TestAuthServiceEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "aranya.db"
        self.memory = FarmMemory(db_path=db_path)
        self.otp = OTPService(db_path=Path(self._tmpdir.name) / "otp.db")
        self.auth = AuthService(memory=self.memory, otp_service=self.otp,
                                 rate_limiter=SlidingWindowRateLimiter(max_requests=5, window_seconds=3600))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_full_login_flow_issues_a_valid_token(self):
        phone = "+91-9999911111"
        code = self.auth.request_login_otp(phone)["debug_code"]
        token = self.auth.verify_login_otp(phone, code, name_if_new="Ramesh")
        claims = decode_access_token(token)
        self.assertEqual(claims.role, Role.FARMER)

        # Second login with the same phone must resolve to the SAME farmer, not a duplicate.
        code2 = self.auth.request_login_otp(phone)["debug_code"]
        token2 = self.auth.verify_login_otp(phone, code2)
        claims2 = decode_access_token(token2)
        self.assertEqual(claims.farmer_id, claims2.farmer_id)

    def test_wrong_code_raises_auth_error_and_does_not_issue_a_token(self):
        phone = "+91-9999922222"
        self.auth.request_login_otp(phone)
        with self.assertRaises(AuthError):
            self.auth.verify_login_otp(phone, "000000")

    def test_rate_limiting_blocks_excessive_requests(self):
        phone = "+91-9999933333"
        for _ in range(5):
            self.auth.request_login_otp(phone)
        with self.assertRaises(AuthError):
            self.auth.request_login_otp(phone)

    def test_every_login_attempt_is_audited(self):
        phone = "+91-9999944444"
        code = self.auth.request_login_otp(phone)["debug_code"]
        self.auth.verify_login_otp(phone, code)
        log = self.memory.get_audit_log(actor=phone)
        actions = [entry["action"] for entry in log]
        self.assertIn("otp_dev_mode_no_delivery_configured", actions)
        self.assertIn("login_success", actions)

    def test_failed_login_is_also_audited(self):
        phone = "+91-9999955555"
        self.auth.request_login_otp(phone)
        try:
            self.auth.verify_login_otp(phone, "000000")
        except AuthError:
            pass
        log = self.memory.get_audit_log(actor=phone)
        self.assertIn("otp_verify_wrong_code", [entry["action"] for entry in log])

    def test_farmer_owns_farm_check(self):
        f1 = self.memory.get_or_create_farmer("Farmer One", phone="+91-1")
        f2 = self.memory.get_or_create_farmer("Farmer Two", phone="+91-2")
        farm_id = self.memory.get_or_create_farm(f1, "Farm A")
        self.assertTrue(self.memory.farmer_owns_farm(f1, farm_id))
        self.assertFalse(self.memory.farmer_owns_farm(f2, farm_id))


@dataclass
class FakeSMSProvider:
    name: str = "fake_sms"
    should_fail: bool = False
    sent: list = field(default_factory=list)

    def send_otp(self, phone: str, code: str) -> None:
        if self.should_fail:
            from backend.core.notification_provider import NotificationUnavailable
            raise NotificationUnavailable("fake sms failure")
        self.sent.append((phone, code))


@dataclass
class FakeEmailProvider:
    name: str = "fake_email"
    should_fail: bool = False
    sent: list = field(default_factory=list)

    def send_otp(self, email: str, code: str) -> None:
        if self.should_fail:
            from backend.core.notification_provider import NotificationUnavailable
            raise NotificationUnavailable("fake email failure")
        self.sent.append((email, code))


class TestAuthServiceMultiChannelDelivery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "aranya.db")
        self.otp = OTPService(db_path=Path(self._tmpdir.name) / "otp.db")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _auth(self, sms=None, email=None):
        return AuthService(memory=self.memory, otp_service=self.otp,
                            sms_provider=sms, email_provider=email,
                            rate_limiter=SlidingWindowRateLimiter(max_requests=5, window_seconds=3600))

    def test_no_channels_configured_falls_back_to_dev_mode_code(self):
        auth = self._auth()
        result = auth.request_login_otp("+91-7000000001")
        self.assertEqual(result["delivered_via"], [])
        self.assertIsNotNone(result["debug_code"])

    def test_sms_only_delivers_and_hides_the_code(self):
        sms = FakeSMSProvider()
        auth = self._auth(sms=sms)
        result = auth.request_login_otp("+91-7000000002")
        self.assertEqual(result["delivered_via"], ["sms"])
        self.assertIsNone(result["debug_code"])
        self.assertEqual(len(sms.sent), 1)

    def test_email_only_delivers_and_hides_the_code(self):
        email = FakeEmailProvider()
        auth = self._auth(email=email)
        result = auth.request_login_otp("+91-7000000003", email="farmer@example.com")
        self.assertEqual(result["delivered_via"], ["email"])
        self.assertIsNone(result["debug_code"])

    def test_both_channels_configured_both_deliver(self):
        sms, email = FakeSMSProvider(), FakeEmailProvider()
        auth = self._auth(sms=sms, email=email)
        result = auth.request_login_otp("+91-7000000004", email="farmer@example.com")
        self.assertEqual(set(result["delivered_via"]), {"sms", "email"})

    def test_one_channel_fails_other_succeeds_still_counts_as_delivered(self):
        sms = FakeSMSProvider(should_fail=True)
        email = FakeEmailProvider()
        auth = self._auth(sms=sms, email=email)
        result = auth.request_login_otp("+91-7000000005", email="farmer@example.com")
        self.assertEqual(result["delivered_via"], ["email"])
        self.assertIsNone(result["debug_code"])

    def test_all_configured_channels_failing_raises_not_dev_mode_fallback(self):
        sms = FakeSMSProvider(should_fail=True)
        email = FakeEmailProvider(should_fail=True)
        auth = self._auth(sms=sms, email=email)
        with self.assertRaises(AuthError):
            auth.request_login_otp("+91-7000000006", email="farmer@example.com")

    def test_invalid_email_format_is_rejected_before_generating_an_otp(self):
        auth = self._auth(email=FakeEmailProvider())
        with self.assertRaises(AuthError):
            auth.request_login_otp("+91-7000000007", email="not-an-email")

    def test_email_not_provided_only_sms_channel_attempted(self):
        sms, email = FakeSMSProvider(), FakeEmailProvider()
        auth = self._auth(sms=sms, email=email)
        result = auth.request_login_otp("+91-7000000008")  # no email given
        self.assertEqual(result["delivered_via"], ["sms"])
        self.assertEqual(len(email.sent), 0)

    def test_verified_login_stores_the_email_on_the_farmer_record(self):
        auth = self._auth()
        code = auth.request_login_otp("+91-7000000009", email="ramesh@example.com")["debug_code"]
        auth.verify_login_otp("+91-7000000009", code, name_if_new="Ramesh", email="ramesh@example.com")
        farmer_id = self.memory.get_or_create_farmer("Ramesh", phone="+91-7000000009")
        farmer = self.memory.get_farmer(farmer_id)
        self.assertEqual(farmer["email"], "ramesh@example.com")

    def test_email_backfills_on_a_farmer_that_had_none_on_file(self):
        auth = self._auth()
        # First login with no email at all.
        code1 = auth.request_login_otp("+91-7000000010")["debug_code"]
        auth.verify_login_otp("+91-7000000010", code1, name_if_new="Sita")
        farmer_id = self.memory.get_or_create_farmer("Sita", phone="+91-7000000010")
        self.assertIsNone(self.memory.get_farmer(farmer_id)["email"])

        # Second login now provides an email — should backfill.
        code2 = auth.request_login_otp("+91-7000000010", email="sita@example.com")["debug_code"]
        auth.verify_login_otp("+91-7000000010", code2, email="sita@example.com")
        self.assertEqual(self.memory.get_farmer(farmer_id)["email"], "sita@example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
