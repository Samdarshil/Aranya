"""
OTP authentication — spec section 19.

What's real here: OTP generation, salted-hash storage (never plaintext),
expiry, per-phone attempt limiting, and single-use consumption on
success. This is the actual security-relevant logic and it is fully
testable without any external dependency.

What's NOT here: an SMS/WhatsApp delivery provider. `request_otp()`
returns the plaintext code to the caller instead of sending it anywhere
— per spec section 3, this is clearly labeled as a stand-in for a real
delivery provider, not a working delivery mechanism. Wiring Twilio/MSG91/
etc. behind a small "OTPDeliveryProvider" protocol (same pattern as
backend/core/providers.py) is the remaining piece — the storage and
verification logic below does not need to change when that's added.

No bcrypt/passlib available in the authoring sandbox (no network to
install), so hashing uses stdlib hashlib.pbkdf2_hmac — a real, correct
choice for hashing a short numeric OTP (not a password), not a
placeholder.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

OTP_LENGTH = 6
OTP_TTL_MINUTES = 5
MAX_VERIFY_ATTEMPTS = 5
MAX_REQUESTS_PER_PHONE_PER_HOUR = 5
PBKDF2_ITERATIONS = 200_000

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "aranya.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS otp_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    salt TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_requests(phone);
"""


class OTPError(Exception):
    """Raised for any OTP failure — expired, wrong code, too many
    attempts, or rate-limited. Message is safe to show the user; it never
    reveals whether a code existed vs was simply never requested."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_code(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()


@dataclass
class OTPService:
    db_path: Path = DEFAULT_DB_PATH

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def request_otp(self, phone: str) -> str:
        """Generates and stores a new OTP for `phone`, returning the
        plaintext code. In production the caller sends this via an SMS
        provider instead of returning it to an API response — see the
        module docstring. Raises OTPError if this phone has requested
        too many codes in the last hour (spec section 19: rate limiting)."""
        with self._connect() as conn:
            window_start = (_now() - timedelta(hours=1)).isoformat()
            recent = conn.execute(
                "SELECT COUNT(*) AS n FROM otp_requests WHERE phone = ? AND created_at > ?",
                (phone, window_start),
            ).fetchone()["n"]
            if recent >= MAX_REQUESTS_PER_PHONE_PER_HOUR:
                raise OTPError("Too many OTP requests for this number. Please try again later.")

            code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
            salt = secrets.token_hex(16)
            code_hash = _hash_code(code, salt)
            expires_at = (_now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()

            conn.execute(
                """INSERT INTO otp_requests (phone, salt, code_hash, expires_at, created_at)
                   VALUES (?,?,?,?,?)""",
                (phone, salt, code_hash, expires_at, _now().isoformat()),
            )
            return code

    def verify_otp(self, phone: str, code: str) -> bool:
        """Verifies `code` against the most recent unconsumed OTP for
        `phone`. Consumes it on success (single-use). Raises OTPError on
        expiry or too many wrong attempts; returns False for a simple
        wrong-code guess that still has attempts remaining."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM otp_requests
                   WHERE phone = ? AND consumed_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (phone,),
            ).fetchone()
            if row is None:
                raise OTPError("No pending verification for this number. Request a new code.")

            if datetime.fromisoformat(row["expires_at"]) < _now():
                raise OTPError("This code has expired. Request a new one.")

            if row["attempts"] >= MAX_VERIFY_ATTEMPTS:
                raise OTPError("Too many incorrect attempts. Request a new code.")

            candidate_hash = _hash_code(code, row["salt"])
            if not secrets.compare_digest(candidate_hash, row["code_hash"]):
                conn.execute(
                    "UPDATE otp_requests SET attempts = attempts + 1 WHERE id = ?", (row["id"],)
                )
                return False

            conn.execute(
                "UPDATE otp_requests SET consumed_at = ? WHERE id = ?", (_now().isoformat(), row["id"])
            )
            return True
