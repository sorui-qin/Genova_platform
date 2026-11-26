from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import User
from backend.security import access_matches_user, decode_access_token
from backend.security import hash_token
from backend.utils import utcnow


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _resolve_guest_user(db: Session, guest_code: str | None) -> User | None:
    raw_code = str(guest_code or "").strip()
    if not raw_code:
        return None

    user = db.query(User).filter(User.guest_code_hash == hash_token(raw_code), User.is_guest.is_(True)).first()
    if user is None or not user.is_active:
        return None
    if user.guest_code_expires_at is not None and user.guest_code_expires_at <= utcnow():
        return None
    user.guest_code_last_used_at = utcnow()
    db.commit()
    return user


def get_current_user(
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
    x_guest_code: str | None = Header(default=None),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token:
        try:
            payload = decode_access_token(token)
            user_id = UUID(str(payload.get("sub", "")))
            user = db.get(User, user_id)
            if access_matches_user(payload, user):
                return user
        except Exception:
            pass

    guest_user = _resolve_guest_user(db, x_guest_code)
    if guest_user is not None:
        return guest_user

    raise unauthorized


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
