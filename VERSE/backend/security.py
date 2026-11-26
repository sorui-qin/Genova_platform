import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from passlib.context import CryptContext

from backend.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: UUID, password_hash: str) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    ttl_seconds = settings.access_token_expire_minutes * 60
    payload = {
        "sub": str(user_id),
        "type": "access",
        "pwd": password_fingerprint(password_hash),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl_seconds


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                         options={"require": ["sub", "exp", "pwd"]})
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("invalid token type")
    return payload


def access_matches_user(payload, user) -> bool:
    return bool(user is not None and user.is_active
                and secrets.compare_digest(str(payload.get("pwd", "")), password_fingerprint(user.password_hash)))


PASSWORD_RESET_MINUTES = 30


def password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(user_id: UUID, password_hash: str) -> str:
    # Bound to the current hash, so the link stops working once any password change lands.
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "password_reset",
        "pwd": password_fingerprint(password_hash),
        "exp": int((now + timedelta(minutes=PASSWORD_RESET_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_password_reset_token(token: str) -> tuple[UUID, str] | None:
    """(user id, password fingerprint) of an unexpired reset link."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "password_reset":
            return None
        return UUID(payload["sub"]), str(payload["pwd"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

