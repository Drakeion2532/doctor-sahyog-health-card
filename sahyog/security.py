"""Security primitives: field-level encryption, signed QR tokens, patient IDs,
PIN lockout and role checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, current_app
from flask_login import current_user


# ---------- field encryption (data at rest) ----------
def _fernet() -> Fernet:
    key = current_app.config["FIELD_ENCRYPTION_KEY"]
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(text: str | None) -> str | None:
    if text in (None, ""):
        return text
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if token in (None, ""):
        return token
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return "[unreadable – wrong encryption key]"


# ---------- unique patient identity number ----------
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I confusion on printed cards


def _check_char(body: str) -> str:
    total = sum((i + 1) * _ALPHABET.index(c) for i, c in enumerate(body))
    return _ALPHABET[total % len(_ALPHABET)]


def new_patient_id() -> str:
    """Format DS-XXXX-XXXX-C (C = check character catches typos at the desk)."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"DS-{body[:4]}-{body[4:]}-{_check_char(body)}"


def valid_patient_id(pid: str) -> bool:
    try:
        prefix, a, b, c = pid.strip().upper().split("-")
    except ValueError:
        return False
    body = a + b
    return (prefix == "DS" and len(body) == 8 and all(ch in _ALPHABET for ch in body)
            and c == _check_char(body))


# ---------- QR-code tokens ----------
def qr_token(patient_id: str, version: int) -> str:
    """HMAC-signed token printed in the QR code. Contains no medical data.
    Bumping `version` (patient clicks 'reissue card') revokes old cards."""
    msg = f"{patient_id}:{version}".encode()
    sig = hmac.new(current_app.config["SECRET_KEY"].encode(), msg, hashlib.sha256).digest()[:SIG_LEN]
    return base64.urlsafe_b64encode(msg + b"." + sig).decode().rstrip("=")


SIG_LEN = 16


def parse_qr_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        # The signature is raw bytes and can itself contain b".", so split by its fixed
        # length rather than on the separator (splitting on "." broke ~6% of genuine cards).
        msg, sep, sig = raw[:-SIG_LEN - 1], raw[-SIG_LEN - 1:-SIG_LEN], raw[-SIG_LEN:]
        if sep != b"." or len(sig) != SIG_LEN:
            return None
        good = hmac.new(current_app.config["SECRET_KEY"].encode(), msg, hashlib.sha256).digest()[:SIG_LEN]
        if not hmac.compare_digest(sig, good):
            return None
        pid, version = msg.decode().split(":")
        return pid, int(version)
    except Exception:
        return None


# ---------- PIN brute-force protection ----------
MAX_PIN_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)


def pin_locked(patient) -> bool:
    if patient.pin_locked_until is None:
        return False
    until = patient.pin_locked_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > datetime.now(timezone.utc)


def register_pin_failure(patient):
    patient.pin_failures = (patient.pin_failures or 0) + 1
    if patient.pin_failures >= MAX_PIN_ATTEMPTS:
        patient.pin_locked_until = datetime.now(timezone.utc) + LOCKOUT
        patient.pin_failures = 0


# ---------- role based access control ----------
def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            if current_user.role == "doctor" and not current_user.doctor_verified:
                abort(403, "Doctor account awaiting verification by admin")
            return fn(*a, **kw)
        return wrapper
    return deco


def generate_key() -> str:
    return Fernet.generate_key().decode()
